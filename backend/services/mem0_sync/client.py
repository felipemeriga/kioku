"""Mem0 client — talks to the self-hosted kioku mem0 service over HTTP.

Memory is auto-on for **repo** folders: any folder with `kind == 'repo'` gets a
client, no per-folder "paste your API key" configuration. The hosted Mem0
platform (and the `mem0_sync_configs` table) is no longer used.

Scoping is enforced service-side by (user_id, agent_id=folder_id); this client
just carries those ids on every call. Reads degrade to `[]` and writes to
`{"ok": False, ...}` when the service is unreachable — the session-start hook
must never crash.
"""

from __future__ import annotations

import logging

from . import http
from .schema import (
    EPISODIC_SCOPE,
    ETERNAL_SCOPE,
    MemoryRecord,
)

log = logging.getLogger(__name__)


# Match up with what memory the retrieval fan-out asks for.
class MemoryScope:
    ETERNAL = ETERNAL_SCOPE
    EPISODIC = EPISODIC_SCOPE
    ANY = "any"


def get_client_for_folder(sb, folder_id: str, user_id: str) -> "Mem0AppClient | None":
    """Return a client for a repo folder, else None.

    Memory is auto-on for repos: the folder just needs `kind == 'repo'` and to
    belong to the user. None means "not a repo folder" — absence is not an error.
    """
    row = (
        sb.table("folders")
        .select("kind")
        .eq("id", folder_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
    )
    if not row or (row[0].get("kind") or "folder") != "repo":
        return None
    return Mem0AppClient(user_id=user_id, folder_id=folder_id)


class Mem0AppClient:
    """Thin HTTP client for the self-hosted mem0 service. Same public surface as
    the previous hosted wrapper so callers are unchanged."""

    def __init__(self, user_id: str, folder_id: str):
        self.user_id = user_id
        self.folder_id = folder_id

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
        """Write a memory. The service stores verbatim (infer=False) and dedups
        by content hash, returning `{ok, memory_id, duplicate}`."""
        try:
            res = http.call(
                "POST",
                "/memories",
                {
                    "user_id": self.user_id,
                    "folder_id": self.folder_id,
                    "content": content,
                    "scope": scope,
                    "category": category,
                    "tags": tags or [],
                    "written_by": written_by,
                },
            )
        except Exception as e:  # noqa: BLE001 — degrade, never raise
            log.exception("mem0 add failed: %s", e)
            return {"ok": False, "error": str(e)}
        # Back-compat: callers (mcp save_memory) read `existing_id`/`raw`.
        res.setdefault("ok", True)
        if res.get("duplicate"):
            res.setdefault("existing_id", res.get("memory_id"))
        res.setdefault(
            "raw", {"memory_id": res.get("memory_id"), "duplicate": res.get("duplicate")}
        )
        return res

    def delete(self, memory_id: str) -> dict:
        try:
            http.call("DELETE", f"/memories/{memory_id}")
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            log.exception("mem0 delete failed: %s", e)
            return {"ok": False, "error": str(e)}

    # ── reads (degrade to [] on failure) ──────────────────────────────────
    def search(
        self,
        query: str,
        *,
        scope: str = MemoryScope.ANY,
        limit: int = 10,
    ) -> list[MemoryRecord]:
        try:
            return http.call(
                "POST",
                "/memories/search",
                {
                    "user_id": self.user_id,
                    "folder_id": self.folder_id,
                    "query": query,
                    "scope": scope,
                    "limit": limit,
                },
            ).get("results", [])
        except Exception as e:  # noqa: BLE001
            log.exception("mem0 search failed: %s", e)
            return []

    def get_all(
        self,
        *,
        scope: str = MemoryScope.ANY,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        try:
            return http.call(
                "POST",
                "/memories/list",
                {
                    "user_id": self.user_id,
                    "folder_id": self.folder_id,
                    "scope": scope,
                    "limit": limit,
                },
            ).get("results", [])
        except Exception as e:  # noqa: BLE001
            log.exception("mem0 get_all failed: %s", e)
            return []

    # ── convenience ───────────────────────────────────────────────────────
    def list_eternal(self, limit: int = 50) -> list[MemoryRecord]:
        """Every eternal preference for this folder — the session-start payload."""
        return self.get_all(scope=MemoryScope.ETERNAL, limit=limit)

    def list_recent_episodic(self, days: int = 14, limit: int = 30) -> list[MemoryRecord]:
        """Recent episodic memories (time-ordered by the service)."""
        return self.get_all(scope=MemoryScope.EPISODIC, limit=limit)

    def deduplicate(
        self,
        *,
        dry_run: bool = True,
        semantic: bool = True,
        similarity_threshold: float = 0.75,
    ) -> dict:
        """No-op: the service dedups by content hash at write time, so there are
        no exact duplicates to reconcile. Kept for API compatibility."""
        return {
            "ok": True,
            "note": "dedup handled by content-hash at write time",
            "dry_run": dry_run,
            "semantic": semantic,
            "similarity_threshold": similarity_threshold,
            "before": 0,
            "kept": 0,
            "removed": 0,
            "clusters": [],
            "keep": [],
            "delete": [],
        }

    def ping(self) -> tuple[bool, str | None]:
        """Cheap connectivity check — is the service reachable and healthy."""
        try:
            ok = http.call("GET", "/health").get("ok", False)
            return bool(ok), None
        except Exception as e:  # noqa: BLE001
            return False, str(e)
