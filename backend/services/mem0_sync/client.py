"""Mem0 cloud client — one client per folder, cached by config id.

Design choices:
- We use `user_id = app_user_id` on every Mem0 call so different agentic-rag
  users have isolated memory spaces even if they somehow share a Mem0 org.
- Folder scoping is done via metadata.folder_id filter, not user_id, so a
  user's memories across folders live in one Mem0 account.
- We cache MemoryClient instances by config_id (60s TTL) to avoid re-auth
  on every proxy call.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from mem0 import MemoryClient

from services.crypto import decrypt_secret

from .schema import (
    EPISODIC_SCOPE,
    ETERNAL_SCOPE,
    MemoryRecord,
    build_metadata,
)

log = logging.getLogger(__name__)


# Match up with what memory the retrieval fan-out asks for.
class MemoryScope:
    ETERNAL = ETERNAL_SCOPE
    EPISODIC = EPISODIC_SCOPE
    ANY = "any"


@dataclass
class _CachedClient:
    client: MemoryClient
    created_at: float


_CACHE_TTL_S = 60.0
_CLIENT_CACHE: dict[str, _CachedClient] = {}


def _build_client(api_key: str, org_id: str | None, project_id: str | None) -> MemoryClient:
    """Instantiate a cloud MemoryClient. Org/project are optional for solo accounts."""
    kwargs: dict[str, Any] = {"api_key": api_key}
    if org_id:
        kwargs["org_id"] = org_id
    if project_id:
        kwargs["project_id"] = project_id
    return MemoryClient(**kwargs)


def _get_or_build_client(config: dict) -> MemoryClient:
    cid = config["id"]
    cached = _CLIENT_CACHE.get(cid)
    now = time.time()
    if cached and (now - cached.created_at) < _CACHE_TTL_S:
        return cached.client
    api_key = decrypt_secret(config["api_key_encrypted"])
    client = _build_client(api_key, config.get("org_id"), config.get("project_id"))
    _CLIENT_CACHE[cid] = _CachedClient(client=client, created_at=now)
    return client


def get_client_for_folder(sb, folder_id: str, user_id: str) -> "Mem0AppClient | None":
    """Load the Mem0 config for (user, folder). Returns None if no integration
    is configured — that's the 'lazy configuration' path: absence is not an error.
    """
    row = (
        sb.table("mem0_sync_configs")
        .select("*")
        .eq("user_id", user_id)
        .eq("root_folder_id", folder_id)
        .limit(1)
        .execute()
        .data
    )
    if not row:
        return None
    return Mem0AppClient(config=row[0], user_id=user_id, folder_id=folder_id)


class Mem0AppClient:
    """Our wrapper around Mem0's MemoryClient. Enforces our metadata schema
    and folder scoping on every read + write."""

    def __init__(self, config: dict, user_id: str, folder_id: str):
        self._config = config
        self.user_id = user_id
        self.folder_id = folder_id

    @property
    def _client(self) -> MemoryClient:
        return _get_or_build_client(self._config)

    # ── writes ────────────────────────────────────────────────────────────
    def add(
        self,
        content: str,
        *,
        scope: str = EPISODIC_SCOPE,
        category: str = "note",
        tags: list[str] | None = None,
        written_by: str = "claude-code",
    ) -> dict:
        """Write a memory. Content is a single-line string carrying the fact.

        We pass infer=False so Mem0 stores the content verbatim rather than
        running its LLM fact-extractor. That extractor is designed for raw
        conversation transcripts — but our writes come from agents that have
        ALREADY decided what to remember. Letting the extractor filter or
        rephrase would break the contract with the caller.
        """
        metadata = build_metadata(
            folder_id=self.folder_id,
            scope=scope,
            category=category,
            tags=tags,
            written_by=written_by,
        )
        try:
            result = self._client.add(
                messages=content,
                user_id=self.user_id,
                metadata=metadata,
                infer=False,
            )
            return {"ok": True, "raw": result, "metadata": metadata}
        except Exception as e:
            log.exception("mem0 add failed: %s", e)
            return {"ok": False, "error": str(e), "metadata": metadata}

    def delete(self, memory_id: str) -> dict:
        try:
            self._client.delete(memory_id=memory_id)
            return {"ok": True}
        except Exception as e:
            log.exception("mem0 delete failed: %s", e)
            return {"ok": False, "error": str(e)}

    # ── reads ─────────────────────────────────────────────────────────────
    def _base_filters(self, scope: str = MemoryScope.ANY) -> dict:
        """Build the Mem0 v2 filter expression that pins to this folder."""
        clauses: list[dict] = [
            {"user_id": self.user_id},
            {"metadata": {"folder_id": self.folder_id}},
        ]
        if scope != MemoryScope.ANY:
            clauses.append({"metadata": {"scope": scope}})
        return {"AND": clauses}

    @staticmethod
    def _unwrap_results(raw) -> list[MemoryRecord]:
        """Mem0 v2 returns `{"results": [...]}` for search/get_all; v1 returns
        a bare list. Normalize both."""
        if raw is None:
            return []
        if isinstance(raw, dict):
            return list(raw.get("results") or raw.get("memories") or [])
        if isinstance(raw, list):
            return list(raw)
        return []

    def search(
        self,
        query: str,
        *,
        scope: str = MemoryScope.ANY,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        try:
            raw = self._client.search(
                query=query,
                filters=self._base_filters(scope=scope),
                limit=limit,
                version="v2",
            )
            return self._unwrap_results(raw)
        except Exception as e:
            log.exception("mem0 search failed: %s", e)
            return []

    def get_all(
        self,
        *,
        scope: str = MemoryScope.ANY,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        try:
            raw = self._client.get_all(
                filters=self._base_filters(scope=scope),
                limit=limit,
                version="v2",
            )
            return self._unwrap_results(raw)
        except Exception as e:
            log.exception("mem0 get_all failed: %s", e)
            return []

    # ── convenience ───────────────────────────────────────────────────────
    def list_eternal(self, limit: int = 50) -> list[MemoryRecord]:
        """Return every eternal preference for this folder. Fast path for the
        session-start orientation payload."""
        return self.get_all(scope=MemoryScope.ETERNAL, limit=limit)

    def list_recent_episodic(self, days: int = 14, limit: int = 30) -> list[MemoryRecord]:
        """Recent episodic memories. Mem0's get_all is time-ordered; we take
        the top N and let callers post-filter by created_at if they need."""
        return self.get_all(scope=MemoryScope.EPISODIC, limit=limit)

    def ping(self) -> tuple[bool, str | None]:
        """Cheap connectivity check — used by the Test-connection button."""
        try:
            self._client.users()  # lightweight and always works with a valid key
            return True, None
        except AttributeError:
            # older SDK: fall back to a shallow get_all
            try:
                self._client.get_all(
                    filters={"AND": [{"user_id": self.user_id}]},
                    limit=1,
                    version="v2",
                )
                return True, None
            except Exception as e:
                return False, str(e)
        except Exception as e:
            return False, str(e)
