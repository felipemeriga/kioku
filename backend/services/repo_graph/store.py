"""Merge per-file deltas into the code graph and query it (Postgres/Supabase).

Merge model (mirrors the extractor's ownership rules):
  * A symbol is owned by its `file`; an edge by its `ref_file`. Re-indexing a
    file replaces all rows it owns — DELETE by file, then insert.
  * Node IDs are deterministic, so cross-file edges resolve by ID. Dangling
    edges (endpoint missing) are dropped at QUERY time (fail-closed) rather
    than eagerly recomputed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.repo_graph.mapping import files_from_nodes, map_edge, map_node

_INSERT_CHUNK = 500
_IN_CHUNK = 100


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def apply_delta(
    sb,
    *,
    folder_id: str,
    user_id: str,
    changed_files: list[str],
    deleted_files: list[str],
    nodes: list[dict],
    edges: list[dict],
    head_sha: str | None,
) -> dict:
    """Replace the graph rows owned by changed/deleted files with the incoming
    delta. `nodes`/`edges` are RAW Graphify dicts for the changed files."""
    changed = {str(f) for f in changed_files}
    deleted = {str(f) for f in deleted_files}

    mapped_nodes = [r for n in nodes if (r := map_node(n, folder_id=folder_id, user_id=user_id))]
    mapped_edges = [r for e in edges if (r := map_edge(e, folder_id=folder_id, user_id=user_id))]

    # Shrink guard: a changed file that yields ZERO nodes but currently HAS
    # nodes is almost certainly a truncated/failed parse (not a real emptying).
    # Skip replacing it — keep the existing rows — unless it was declared
    # deleted. This prevents a bad extraction from wiping the graph.
    incoming_files = files_from_nodes(nodes)
    skipped: list[str] = []
    for f in changed - deleted:
        if f in incoming_files:
            continue
        existing = (
            sb.table("repo_symbols")
            .select("node_id", count="exact")
            .eq("folder_id", folder_id)
            .eq("file", f)
            .execute()
            .count
        ) or 0
        if existing > 0:
            skipped.append(f)

    replace_files = (changed - set(skipped)) | deleted
    if skipped:
        mapped_nodes = [r for r in mapped_nodes if r["file"] not in skipped]
        mapped_edges = [r for r in mapped_edges if r.get("ref_file") not in skipped]

    # Per-file replace: delete everything owned by the affected files first.
    affected = sorted(replace_files)
    for batch in _chunks(affected, _IN_CHUNK):
        sb.table("repo_symbols").delete().eq("folder_id", folder_id).in_("file", batch).execute()
        sb.table("repo_edges").delete().eq("folder_id", folder_id).in_("ref_file", batch).execute()

    # Insert the new rows. Upsert nodes on the (folder_id, node_id) PK so a
    # symbol that legitimately appears twice in one delta doesn't 409.
    for batch in _chunks(mapped_nodes, _INSERT_CHUNK):
        sb.table("repo_symbols").upsert(batch, on_conflict="folder_id,node_id").execute()
    for batch in _chunks(mapped_edges, _INSERT_CHUNK):
        sb.table("repo_edges").insert(batch).execute()

    node_count = (
        sb.table("repo_symbols")
        .select("node_id", count="exact")
        .eq("folder_id", folder_id)
        .execute()
        .count
    ) or 0
    edge_count = (
        sb.table("repo_edges")
        .select("id", count="exact")
        .eq("folder_id", folder_id)
        .execute()
        .count
    ) or 0
    sb.table("repo_graph_meta").upsert(
        {
            "folder_id": folder_id,
            "user_id": user_id,
            "last_indexed_sha": head_sha,
            "node_count": node_count,
            "edge_count": edge_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="folder_id",
    ).execute()

    return {
        "nodes_upserted": len(mapped_nodes),
        "edges_upserted": len(mapped_edges),
        "files_replaced": sorted(replace_files),
        "skipped_shrink": skipped,
        "node_count": node_count,
        "edge_count": edge_count,
    }


# ── queries ──────────────────────────────────────────────────────────


def find_definition(sb, *, folder_id: str, symbol: str, limit: int = 20) -> list[dict]:
    """Symbols matching `symbol` (exact first, then substring)."""
    exact = (
        sb.table("repo_symbols")
        .select("node_id,symbol,kind,file,start_line")
        .eq("folder_id", folder_id)
        .eq("symbol", symbol)
        .limit(limit)
        .execute()
        .data
    ) or []
    if exact:
        return exact
    return (
        sb.table("repo_symbols")
        .select("node_id,symbol,kind,file,start_line")
        .eq("folder_id", folder_id)
        .ilike("symbol", f"%{symbol}%")
        .limit(limit)
        .execute()
        .data
    ) or []


def _existing_node_ids(sb, folder_id: str, node_ids: list[str]) -> set[str]:
    found: set[str] = set()
    for batch in _chunks(list(node_ids), _IN_CHUNK):
        rows = (
            sb.table("repo_symbols")
            .select("node_id")
            .eq("folder_id", folder_id)
            .in_("node_id", batch)
            .execute()
            .data
        ) or []
        found.update(r["node_id"] for r in rows)
    return found


def find_references(sb, *, folder_id: str, symbol: str, limit: int = 100) -> list[dict]:
    """Edges pointing AT the symbol (who calls/references it). Fail-closed:
    only edges whose source node still exists are returned."""
    targets = find_definition(sb, folder_id=folder_id, symbol=symbol, limit=50)
    target_ids = [t["node_id"] for t in targets]
    if not target_ids:
        return []
    edges: list[dict] = []
    for batch in _chunks(target_ids, _IN_CHUNK):
        rows = (
            sb.table("repo_edges")
            .select("src_node_id,dst_node_id,relation,ref_file,ref_line")
            .eq("folder_id", folder_id)
            .in_("dst_node_id", batch)
            .limit(limit)
            .execute()
            .data
        ) or []
        edges.extend(rows)
    live = _existing_node_ids(sb, folder_id, [e["src_node_id"] for e in edges])
    return [e for e in edges if e["src_node_id"] in live][:limit]


def outline(sb, *, folder_id: str, path: str, limit: int = 500) -> list[dict]:
    """All symbols under a file or directory prefix, ordered by file then line."""
    return (
        sb.table("repo_symbols")
        .select("node_id,symbol,kind,file,start_line")
        .eq("folder_id", folder_id)
        .ilike("file", f"{path}%")
        .order("file")
        .order("start_line")
        .limit(limit)
        .execute()
        .data
    ) or []


def impact_of(
    sb, *, folder_id: str, symbol: str, depth: int = 2, max_nodes: int = 200
) -> list[dict]:
    """Backward blast-radius: transitive callers/referencers up to `depth`.
    Bounded BFS over repo_edges (fail-closed on existing nodes)."""
    seeds = find_definition(sb, folder_id=folder_id, symbol=symbol, limit=50)
    frontier = {s["node_id"] for s in seeds}
    seen = set(frontier)
    hits: list[dict] = []
    for d in range(1, depth + 1):
        if not frontier or len(seen) >= max_nodes:
            break
        callers: list[dict] = []
        for batch in _chunks(list(frontier), _IN_CHUNK):
            rows = (
                sb.table("repo_edges")
                .select("src_node_id,dst_node_id,relation")
                .eq("folder_id", folder_id)
                .in_("dst_node_id", batch)
                .execute()
                .data
            ) or []
            callers.extend(rows)
        next_ids = {c["src_node_id"] for c in callers} - seen
        if not next_ids:
            break
        live = _existing_node_ids(sb, folder_id, list(next_ids))
        rows = []
        for batch in _chunks(list(live), _IN_CHUNK):
            rows.extend(
                (
                    sb.table("repo_symbols")
                    .select("node_id,symbol,file,start_line")
                    .eq("folder_id", folder_id)
                    .in_("node_id", batch)
                    .execute()
                    .data
                )
                or []
            )
        for r in rows:
            hits.append({**r, "depth": d})
        seen |= live
        frontier = live
    return hits[:max_nodes]
