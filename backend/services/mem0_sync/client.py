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
    compute_dedup_key,
    normalize_content,
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

    # ── scoping ───────────────────────────────────────────────────────────
    # Mem0's cloud service dedups on memory text within a
    # (user_id, agent_id, app_id, run_id) scope — regardless of metadata.
    # If we don't populate agent_id, two different folders with the same
    # content collapse to one shared memory (whose folder_id metadata
    # points at whichever folder created it first). That's the wrong
    # semantics for us: folders are memory namespaces.
    #
    # We use agent_id = folder_id to make each folder its own scope.
    # metadata.folder_id is kept for query readability and legacy rows.
    @property
    def _scope_kwargs(self) -> dict:
        return {"user_id": self.user_id, "agent_id": self.folder_id}

    # ── writes ────────────────────────────────────────────────────────────
    def _find_existing_memory(
        self, *, content_hash: str, content: str
    ) -> MemoryRecord | None:
        """Return the existing memory identical to this content.

        Two-stage lookup:
          1. content_hash metadata filter — hits any prior write of the same
             content in this folder (our own dedup contract).
          2. If (1) misses, fall back to matching on normalized content across
             ALL of the folder's memories. Handles the case where legacy rows
             don't carry content_hash yet.
        """
        try:
            raw = self._client.get_all(
                filters={
                    "AND": [
                        {"user_id": self.user_id},
                        {"metadata": {"folder_id": self.folder_id}},
                        {"metadata": {"content_hash": content_hash}},
                    ]
                },
                limit=1,
                version="v2",
            )
            hits = self._unwrap_results(raw)
            if hits:
                return hits[0]
        except Exception as e:
            log.warning("content-hash lookup failed: %s", e)

        # Fallback for legacy rows (no content_hash yet): compare normalized text.
        try:
            raw = self._client.get_all(
                filters={
                    "AND": [
                        {"user_id": self.user_id},
                        {"metadata": {"folder_id": self.folder_id}},
                    ]
                },
                limit=500,
                version="v2",
            )
            target = normalize_content(content)
            for r in self._unwrap_results(raw):
                if normalize_content(r.get("memory") or "") == target:
                    return r
        except Exception as e:
            log.warning("legacy-content fallback lookup failed: %s", e)
        return None

    def add(
        self,
        content: str,
        *,
        scope: str = EPISODIC_SCOPE,
        category: str = "note",
        tags: list[str] | None = None,
        written_by: str = "claude-code",
    ) -> dict:
        """Write a memory, deduplicating deterministically by content hash.

        Two guarantees this call enforces:

        1. `infer=False` so Mem0 stores content verbatim — no LLM
           fact-extractor filtering or rewriting.
        2. Content-hash dedup: same (folder, scope, category, normalized content)
           produces the same dedup_key and reuses the existing memory. A
           second write bumps the existing row's `updated_at` (mark as
           'seen again') instead of adding a duplicate.
        """
        metadata = build_metadata(
            folder_id=self.folder_id,
            scope=scope,
            category=category,
            tags=tags,
            written_by=written_by,
            content=content,
        )
        content_hash = metadata["content_hash"]

        # Fast-path exact dedup lookup by metadata.content_hash. Aligns with
        # Mem0's own internal dedup on memory text — Mem0 will silently no-op
        # a duplicate write anyway, so we intercept first, reuse the existing
        # id, and update tags rather than getting a silent no-op.
        existing = self._find_existing_memory(
            content_hash=content_hash, content=content
        )
        if existing is not None:
            # Update the existing memory so tags/updated_at reflect the retry.
            # We don't overwrite content — the dedup_key guarantees it's the
            # same normalized text — but we do keep tags fresh.
            merged_tags = sorted(
                set((existing.get("metadata") or {}).get("tags") or []) | set(tags or [])
            )
            try:
                self._client.update(
                    memory_id=existing["id"],
                    metadata={**(existing.get("metadata") or {}), "tags": merged_tags},
                )
            except Exception:  # noqa: BLE001 — non-fatal
                pass
            return {
                "ok": True,
                "duplicate": True,
                "existing_id": existing["id"],
                "metadata": metadata,
                "reason": "exact-content-match",
            }

        try:
            result = self._client.add(
                messages=content,
                metadata=metadata,
                infer=False,
                **self._scope_kwargs,
            )
            return {"ok": True, "duplicate": False, "raw": result, "metadata": metadata}
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
        """Build the Mem0 v2 filter expression that pins to this folder.

        We filter by metadata.folder_id (not agent_id) because Mem0's v2
        filter grammar doesn't support nested OR reliably. Every write goes
        through our proxy which populates BOTH agent_id (for dedup scoping)
        AND metadata.folder_id (for this read query), so the two ids are
        always in sync for new memories. Legacy rows only have folder_id."""
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

    def deduplicate(
        self,
        *,
        dry_run: bool = True,
        semantic: bool = True,
        similarity_threshold: float = 0.75,
    ) -> dict:
        """Reconcile pre-existing duplicates in this folder.

        Two passes:
          1. Exact-match: group by (scope, category, normalized_content).
             Keeps the newest of each group, drops the rest. Fast and safe.
          2. Semantic (optional, on by default): for each surviving memory,
             run a Mem0 search using that memory's own text; hits above
             `similarity_threshold` that aren't the same id AND share scope
             are treated as duplicates. Keeps the newest of the merged
             cluster.

        `semantic=True` catches the pre-`infer=False` legacy case where
        Mem0's fact-extractor rephrased writes (different words, same
        meaning). `semantic=False` restricts to strictly-identical text.

        dry_run=True returns the plan without deleting.
        """
        all_memories = self.get_all(limit=500)

        # Pass 1 — exact match on (scope, category, normalized_content).
        groups: dict[tuple[str, str, str], list[MemoryRecord]] = {}
        for m in all_memories:
            md = m.get("metadata") or {}
            key = (
                md.get("scope") or "unknown",
                md.get("category") or "unknown",
                normalize_content(m.get("memory") or ""),
            )
            groups.setdefault(key, []).append(m)

        exact_delete_ids: set[str] = set()
        survivors: list[MemoryRecord] = []
        for group in groups.values():
            group.sort(
                key=lambda m: m.get("updated_at") or m.get("created_at") or "",
                reverse=True,
            )
            survivors.append(group[0])
            for loser in group[1:]:
                exact_delete_ids.add(loser["id"])

        # Pass 2 — semantic match on survivors.
        semantic_delete: dict[str, str] = {}  # loser_id → winner_id
        clusters: list[dict] = []
        if semantic and len(survivors) > 1:
            handled: set[str] = set()
            # Sort so we probe newest first — they win in a tie.
            survivors.sort(
                key=lambda m: m.get("updated_at") or m.get("created_at") or "",
                reverse=True,
            )
            id_to_mem = {m["id"]: m for m in survivors}
            for m in survivors:
                mid = m["id"]
                if mid in handled:
                    continue
                handled.add(mid)
                scope = (m.get("metadata") or {}).get("scope")
                try:
                    hits = self.search(
                        m.get("memory") or "",
                        scope=scope or MemoryScope.ANY,
                        limit=10,
                    )
                except Exception:  # noqa: BLE001
                    continue
                merged_ids = []
                for h in hits:
                    hid = h.get("id")
                    if not hid or hid == mid or hid in handled:
                        continue
                    score = h.get("score") or 0.0
                    if score < similarity_threshold:
                        continue
                    # Same-scope required so a preference doesn't merge into a note.
                    h_scope = (h.get("metadata") or {}).get("scope")
                    if scope and h_scope and h_scope != scope:
                        continue
                    merged_ids.append(hid)
                    handled.add(hid)
                    semantic_delete[hid] = mid
                if merged_ids:
                    clusters.append({
                        "winner_id": mid,
                        "winner_preview": (m.get("memory") or "")[:80],
                        "merged_ids": merged_ids,
                        "merged_previews": [
                            (id_to_mem.get(x, {}).get("memory") or "")[:80]
                            for x in merged_ids
                        ],
                    })

        # Build the plan.
        keep: list[dict] = []
        delete: list[dict] = []
        deleted_set = exact_delete_ids | set(semantic_delete)
        for m in all_memories:
            md = m.get("metadata") or {}
            row = {
                "id": m["id"],
                "scope": md.get("scope"),
                "category": md.get("category"),
                "preview": (m.get("memory") or "")[:80],
            }
            if m["id"] in deleted_set:
                row["reason"] = (
                    "exact-duplicate" if m["id"] in exact_delete_ids
                    else "semantic-duplicate"
                )
                if m["id"] in semantic_delete:
                    row["winner_id"] = semantic_delete[m["id"]]
                delete.append(row)
            else:
                keep.append(row)

        if not dry_run:
            for row in delete:
                try:
                    self._client.delete(memory_id=row["id"])
                except Exception as e:  # noqa: BLE001
                    row["delete_error"] = str(e)

        return {
            "dry_run": dry_run,
            "semantic": semantic,
            "similarity_threshold": similarity_threshold,
            "before": len(all_memories),
            "kept": len(keep),
            "removed": len(delete),
            "clusters": clusters,
            "keep": keep,
            "delete": delete,
        }

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
