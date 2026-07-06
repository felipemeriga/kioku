"""Supabase access layer for folder-summary generation.

Isolated so the builder can stay pure and testable, and so the same shape of
queries is used by the REST routes and the arq cron.
"""

from __future__ import annotations

from typing import Any


def get_folder(sb, folder_id: str, user_id: str) -> dict | None:
    # Wildcard select so the builder gets `kind` once the Phase 1 migration
    # lands, without needing to touch this helper again. Missing column pre-
    # migration = callers default to 'folder' when reading .get("kind").
    r = (
        sb.table("folders")
        .select("*")
        .eq("id", folder_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return r.data[0] if r.data else None


def get_descendant_folder_ids(sb, folder_id: str, user_id: str) -> list[str]:
    """BFS over folders.parent_id — returns folder_id + all descendants (inclusive)."""
    result = [folder_id]
    frontier = [folder_id]
    while frontier:
        r = (
            sb.table("folders")
            .select("id")
            .in_("parent_id", frontier)
            .eq("user_id", user_id)
            .execute()
        )
        next_ids = [row["id"] for row in (r.data or [])]
        if not next_ids:
            break
        result.extend(next_ids)
        frontier = next_ids
    return result


def get_direct_subfolders(sb, folder_id: str, user_id: str) -> list[dict]:
    r = (
        sb.table("folders")
        .select("id, name")
        .eq("parent_id", folder_id)
        .eq("user_id", user_id)
        .order("name")
        .execute()
    )
    return r.data or []


def count_direct_docs(sb, folder_id: str, user_id: str) -> int:
    """Documents whose folder_id == this folder (NOT descendants). Cheap: a
    HEAD count query with the (user_id, folder_id) index."""
    r = (
        sb.table("documents")
        .select("id", count="exact", head=True)
        .eq("user_id", user_id)
        .eq("folder_id", folder_id)
        .eq("status", "completed")
        .execute()
    )
    return r.count or 0


# A folder is treated as a "container" (aka workspace root) when it has at
# least one subfolder and very few direct docs. That covers the mental
# model of a company/monorepo/notion-workspace root: the real content lives
# a level down under c360-lead/, h265/, nba/, etc.
_CONTAINER_MAX_DIRECT_DOCS = 2


def is_container_folder(sb, folder_id: str, user_id: str) -> bool:
    subs = get_direct_subfolders(sb, folder_id, user_id)
    if not subs:
        return False
    return count_direct_docs(sb, folder_id, user_id) <= _CONTAINER_MAX_DIRECT_DOCS


def get_folder_path(sb, folder_id: str, user_id: str) -> str:
    """Slash-joined breadcrumb from root down to this folder, e.g. 'Projects/agentic-rag'."""
    parts: list[str] = []
    cur: str | None = folder_id
    while cur:
        r = (
            sb.table("folders")
            .select("id, name, parent_id")
            .eq("id", cur)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not r.data:
            break
        parts.append(r.data[0]["name"])
        cur = r.data[0].get("parent_id")
    return "/".join(reversed(parts))


def get_docs_in_subtree(sb, folder_id: str, user_id: str) -> list[dict]:
    """One row per (source_filename) with content concatenated across all chunks.

    We use chunk_index ordering to reconstruct the canonical document text.
    Only completed docs are included so in-flight ingestions don't get summarized.
    """
    folder_ids = get_descendant_folder_ids(sb, folder_id, user_id)

    rows: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        r = (
            sb.table("documents")
            .select("source_filename, content, content_hash, chunk_index, folder_id, status")
            .eq("user_id", user_id)
            .in_("folder_id", folder_ids)
            .eq("status", "completed")
            .order("source_filename")
            .order("chunk_index")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = r.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    # Group by source_filename, concatenate content by chunk_index order.
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        fname = row["source_filename"]
        if fname not in grouped:
            grouped[fname] = {
                "source_filename": fname,
                "chunks": [],
                "hashes": set(),
            }
        grouped[fname]["chunks"].append((row.get("chunk_index") or 0, row.get("content") or ""))
        if row.get("content_hash"):
            grouped[fname]["hashes"].add(row["content_hash"])

    docs: list[dict] = []
    for fname, g in grouped.items():
        g["chunks"].sort(key=lambda t: t[0])
        content = "\n\n".join(txt for _, txt in g["chunks"])
        # doc-level content_hash: sorted union of chunk hashes joined.
        merged_hash = "|".join(sorted(g["hashes"])) if g["hashes"] else ""
        docs.append(
            {
                "source_filename": fname,
                "content": content,
                "content_hash": merged_hash,
                "chunk_count": len(g["chunks"]),
            }
        )
    docs.sort(key=lambda d: d["source_filename"])
    return docs


def get_latest_summary(sb, folder_id: str, user_id: str) -> dict | None:
    r = (
        sb.table("folder_summaries")
        .select("*")
        .eq("folder_id", folder_id)
        .eq("user_id", user_id)
        .order("generated_at", desc=True)
        .limit(1)
        .execute()
    )
    return r.data[0] if r.data else None


_HISTORY_COLS = (
    "id, generated_at, kind, doc_count, changed_files, "
    "input_tokens, output_tokens, duration_ms, trigger"
)


def get_summary_history(sb, folder_id: str, user_id: str, limit: int = 10) -> list[dict]:
    r = (
        sb.table("folder_summaries")
        .select(_HISTORY_COLS)
        .eq("folder_id", folder_id)
        .eq("user_id", user_id)
        .order("generated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return r.data or []


def insert_summary(
    sb,
    *,
    folder_id: str,
    user_id: str,
    kind: str,
    trigger: str,
    content: dict,
    previous_content: dict | None,
    included_hashes: list[dict],
    doc_count: int,
    changed_files: dict,
    input_tokens: int,
    output_tokens: int,
    duration_ms: int,
) -> dict:
    payload = {
        "folder_id": folder_id,
        "user_id": user_id,
        "kind": kind,
        "trigger": trigger,
        "content": content,
        "previous_content": previous_content,
        "included_hashes": included_hashes,
        "doc_count": doc_count,
        "changed_files": changed_files,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "duration_ms": duration_ms,
    }
    # Migration-safe downgrade chain — some DBs haven't widened the
    # trigger_check constraint to allow 'rollup_bootstrap:*'. Downgrade to
    # 'manual' rather than failing the whole regen.
    for _ in range(3):
        try:
            r = sb.table("folder_summaries").insert(payload).execute()
            return r.data[0]
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "trigger_check" in msg and payload.get("trigger") != "manual":
                payload["trigger"] = "manual"
                continue
            raise
    raise RuntimeError("insert_summary exhausted downgrade attempts")


def list_folder_ids_with_docs(sb) -> list[dict]:
    """All (folder_id, user_id) pairs that have at least one completed doc.

    Used by the nightly cron. We enumerate distinct pairs so cron work scales
    with the number of active folders, not with the number of documents.
    """
    rows: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        r = (
            sb.table("documents")
            .select("folder_id, user_id")
            .eq("status", "completed")
            .not_.is_("folder_id", "null")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = r.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size

    seen: set[tuple[str, str]] = set()
    pairs: list[dict] = []
    for row in rows:
        key = (row["folder_id"], row["user_id"])
        if key in seen:
            continue
        seen.add(key)
        pairs.append({"folder_id": row["folder_id"], "user_id": row["user_id"]})
    return pairs


def list_all_regenerable_folder_pairs(sb) -> list[dict]:
    """All (folder_id, user_id) pairs the nightly cron should regenerate.

    Union of:
      1. Folders with completed docs (leaf-summary path).
      2. Every folder with kind='repo' — repos still need regen even
         when doc count is 0 (their briefing pulls in fresh GitHub
         activity + Mem0 preferences even with an empty doc corpus).
      3. Container folders that already have a workspace_rollup row —
         once a workspace has been established, we want its rollup
         refreshed as its children get regenerated.

    Deduped across all three lists.
    """
    pairs: list[dict] = list(list_folder_ids_with_docs(sb))
    seen: set[tuple[str, str]] = {(p["folder_id"], p["user_id"]) for p in pairs}

    # 2. All repo folders (regardless of doc count).
    try:
        repo_rows = (
            sb.table("folders").select("id, user_id, kind")
            .eq("kind", "repo").execute().data or []
        )
        for r in repo_rows:
            key = (r["id"], r["user_id"])
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"folder_id": r["id"], "user_id": r["user_id"]})
    except Exception:  # noqa: BLE001 — migration for kind col may not have run
        pass

    # 3. Container folders with an existing workspace_rollup row.
    try:
        rollup_rows = (
            sb.table("folder_summaries").select("folder_id, user_id")
            .eq("kind", "workspace_rollup").execute().data or []
        )
        for r in rollup_rows:
            key = (r["folder_id"], r["user_id"])
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"folder_id": r["folder_id"], "user_id": r["user_id"]})
    except Exception:  # noqa: BLE001
        pass

    return pairs
