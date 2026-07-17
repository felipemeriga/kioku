"""MemoryStore — OSS mem0 on pgvector, folder-scoped and verbatim.

Mirrors kioku's `services/mem0_sync/schema.py` metadata semantics so memories
written here are shaped identically to the (previously hosted) ones:

  metadata = {folder_id, scope, category, tags, written_by, content_hash, dedup_key}

Scoping: every call is pinned to (user_id, agent_id=folder_id). agent_id is the
folder namespace — two folders never see each other's memories. content_hash is
folder+content only (matching mem0's own content-based dedup); dedup_key adds
scope+category for observability.

All writes use infer=False: content is stored verbatim, no LLM rewriting. The
service needs an embedder but no LLM.
"""

from __future__ import annotations

import hashlib
import re

from mem0 import Memory

from app.config import settings

ETERNAL_SCOPE = "eternal"
EPISODIC_SCOPE = "episodic"
_VALID_SCOPES = (ETERNAL_SCOPE, EPISODIC_SCOPE)
_VALID_CATEGORIES = ("decision", "finding", "issue", "preference", "session", "note")

_WS_RE = re.compile(r"\s+")


def normalize_content(content: str) -> str:
    """Canonical form used for the dedup hash — mirrors schema.py."""
    if not content:
        return ""
    lowered = content.strip().lower()
    collapsed = _WS_RE.sub(" ", lowered)
    return collapsed.rstrip(".!?;:,)]}\"'` ").lstrip("([{\"'` ")


def compute_content_hash(*, content: str, folder_id: str) -> str:
    """Content-only identity: same text in the same folder is the same memory."""
    return hashlib.sha256(
        f"{folder_id}|{normalize_content(content)}".encode()
    ).hexdigest()


def compute_dedup_key(
    *, content: str, folder_id: str, scope: str, category: str
) -> str:
    """Categorical identity: same content + scope + category."""
    payload = f"{folder_id}|{scope}|{category}|{normalize_content(content)}"
    return hashlib.sha256(payload.encode()).hexdigest()


def build_metadata(
    *,
    folder_id: str,
    scope: str = EPISODIC_SCOPE,
    category: str = "note",
    tags: list[str] | None = None,
    written_by: str = "kioku",
    content: str = "",
) -> dict:
    scope = scope if scope in _VALID_SCOPES else EPISODIC_SCOPE
    category = category if category in _VALID_CATEGORIES else "note"
    return {
        "folder_id": folder_id,
        "scope": scope,
        "category": category,
        "tags": list(tags or []),
        "written_by": written_by,
        "content_hash": compute_content_hash(content=content, folder_id=folder_id),
        "dedup_key": compute_dedup_key(
            content=content, folder_id=folder_id, scope=scope, category=category
        ),
    }


def _mem0_config() -> dict:
    return {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "connection_string": settings.database_url,
                "collection_name": "memories",
                "embedding_model_dims": settings.embedder_dims,
            },
        },
        "embedder": {
            "provider": "huggingface",
            "config": {"model": settings.embedder_model},
        },
        # mem0 always instantiates an LLM at init and enforces credentials,
        # even though every write here is infer=False (verbatim, no LLM call).
        # A placeholder key gets past init without requiring a real one — the
        # LLM is never invoked, so the key is never read.
        "llm": {
            "provider": "openai",
            "config": {"api_key": "unused-infer-false", "model": "gpt-4o-mini"},
        },
    }


class MemoryStore:
    """Thin wrapper over mem0's OSS ``Memory``. One instance per process."""

    def __init__(self, memory: Memory | None = None):
        # `memory` injectable for tests; built from config otherwise.
        self._m = memory if memory is not None else Memory.from_config(_mem0_config())

    def _scope_filters(self, user_id: str, folder_id: str) -> dict:
        return {"user_id": user_id, "agent_id": folder_id}

    def add(
        self,
        user_id: str,
        folder_id: str,
        content: str,
        *,
        scope: str,
        category: str,
        tags: list[str] | None = None,
        written_by: str = "kioku",
    ) -> dict:
        md = build_metadata(
            folder_id=folder_id,
            scope=scope,
            category=category,
            tags=tags,
            written_by=written_by,
            content=content,
        )
        existing = self._find_by_hash(user_id, folder_id, md["content_hash"])
        if existing is not None:
            return {"ok": True, "memory_id": existing["id"], "duplicate": True}
        res = self._m.add(
            content,
            user_id=user_id,
            agent_id=folder_id,
            metadata=md,
            infer=False,
        )
        return {"ok": True, "memory_id": self._first_id(res), "duplicate": False}

    def _find_by_hash(
        self, user_id: str, folder_id: str, content_hash: str
    ) -> dict | None:
        for m in self.list(user_id, folder_id, scope="any", limit=500):
            if (m.get("metadata") or {}).get("content_hash") == content_hash:
                return m
        return None

    def list(
        self, user_id: str, folder_id: str, *, scope: str = "any", limit: int = 50
    ) -> list[dict]:
        res = self._m.get_all(
            filters=self._scope_filters(user_id, folder_id), top_k=limit
        )
        return self._filter_scope(self._unwrap(res), scope)

    def search(
        self,
        user_id: str,
        folder_id: str,
        query: str,
        *,
        scope: str = "any",
        limit: int = 10,
    ) -> list[dict]:
        res = self._m.search(
            query, filters=self._scope_filters(user_id, folder_id), top_k=limit
        )
        return self._filter_scope(self._unwrap(res), scope)

    def delete(self, memory_id: str) -> dict:
        try:
            self._m.delete(memory_id=memory_id)
            return {"ok": True}
        except Exception as e:  # noqa: BLE001 — degrade, never raise
            return {"ok": False, "error": str(e)}

    def ping(self) -> tuple[bool, str | None]:
        try:
            self._m.get_all(filters={"user_id": "__ping__"}, top_k=1)
            return True, None
        except Exception as e:  # noqa: BLE001
            return False, str(e)

    @staticmethod
    def _first_id(res) -> str | None:
        items = MemoryStore._unwrap(res)
        return items[0].get("id") if items else None

    @staticmethod
    def _unwrap(res) -> list[dict]:
        if isinstance(res, dict):
            return list(res.get("results") or [])
        return list(res or [])

    @staticmethod
    def _filter_scope(items: list[dict], scope: str | None) -> list[dict]:
        if scope in (None, "any"):
            return items
        return [m for m in items if (m.get("metadata") or {}).get("scope") == scope]
