"""Supabase read helpers shared by the repo-briefing path + read_folder_documents.

Kept minimal after the non-repo folder-summary engine was removed — only the
helpers still used by briefing reads and `read_folder_documents` remain.
"""

from __future__ import annotations

from typing import Any


def get_folder(sb, folder_id: str, user_id: str) -> dict | None:
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


def get_ancestor_folder_ids(sb, folder_id: str, user_id: str) -> list[str]:
    """Ancestor folder ids from the immediate parent up to the root, EXCLUDING
    folder_id itself. Ordered nearest-parent-first. Used to fold shared context
    (e.g. a company root folder's docs) into a repo's briefing."""
    ids: list[str] = []
    seen = {folder_id}
    cur: str | None = folder_id
    # Bound the walk so a cyclic parent_id can't loop forever.
    for _ in range(64):
        r = (
            sb.table("folders")
            .select("parent_id")
            .eq("id", cur)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
            .data
        )
        if not r:
            break
        parent = r[0].get("parent_id")
        if not parent or parent in seen:
            break
        ids.append(parent)
        seen.add(parent)
        cur = parent
    return ids


def get_root_folder_id(sb, folder_id: str, user_id: str) -> str:
    """The topmost ancestor of folder_id (a root has parent_id=null), or
    folder_id itself if it's already a root."""
    ancestors = get_ancestor_folder_ids(sb, folder_id, user_id)
    return ancestors[-1] if ancestors else folder_id


def find_child_folder_id(sb, parent_id: str, name: str, user_id: str) -> str | None:
    """Id of the direct child folder named `name` (case-insensitive) under
    parent_id, or None. Used to locate the 'repositories' container."""
    r = (
        sb.table("folders")
        .select("id")
        .eq("parent_id", parent_id)
        .eq("user_id", user_id)
        .ilike("name", name)
        .limit(1)
        .execute()
        .data
    )
    return r[0]["id"] if r else None


def _reconstruct_docs(sb, folder_ids: list[str], user_id: str) -> list[dict]:
    """One row per (source_filename) with content concatenated across all chunks,
    for documents whose folder_id is in `folder_ids`. Only completed docs.

    We use chunk_index ordering to reconstruct the canonical document text.
    """
    if not folder_ids:
        return []

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


def get_docs_in_subtree(sb, folder_id: str, user_id: str) -> list[dict]:
    """Reconstructed docs for a folder and all its descendants."""
    return _reconstruct_docs(sb, get_descendant_folder_ids(sb, folder_id, user_id), user_id)


def get_docs_for_folder_ids(sb, folder_ids: list[str], user_id: str) -> list[dict]:
    """Reconstructed docs whose folder_id is exactly one of `folder_ids` (the
    folders' own direct docs — not their subtrees)."""
    return _reconstruct_docs(sb, list(folder_ids), user_id)


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
