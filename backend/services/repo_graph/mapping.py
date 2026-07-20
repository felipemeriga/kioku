"""Map raw Graphify node-link JSON into repo_symbols / repo_edges rows.

Kept pure (no DB, no I/O) so the field mapping is unit-testable and lives in
one place — if the extractor's format shifts, only this module changes.

Graphify code-only node shape:
    {"id", "label", "source_file", "source_location": "L12", "file_type",
     "_origin": "ast"}
Graphify edge (link) shape:
    {"source", "target", "relation", "confidence", "source_file",
     "source_location", "weight", "context", "_origin"}
"""

from __future__ import annotations

import re
from typing import Any

_LINE_RE = re.compile(r"(\d+)")


def parse_line(source_location: Any) -> int | None:
    """'L12' / 'L12-L20' / 12 -> 12. Anything unparseable -> None."""
    if source_location is None:
        return None
    if isinstance(source_location, int):
        return source_location
    m = _LINE_RE.search(str(source_location))
    return int(m.group(1)) if m else None


def infer_kind(node: dict) -> str | None:
    """Best-effort kind from Graphify's label conventions (code-only mode has
    no explicit kind). 'file' | 'method' | 'function' | 'symbol'."""
    label = str(node.get("label") or "")
    src = str(node.get("source_file") or "")
    if not label:
        return None
    # A file node's label is the basename of its own source_file.
    if src and label == src.rsplit("/", 1)[-1]:
        return "file"
    if label.startswith("."):
        return "method"
    if label.endswith("()"):
        return "function"
    return "symbol"


def map_node(node: dict, *, folder_id: str, user_id: str) -> dict | None:
    """Graphify node -> repo_symbols row. Returns None if it lacks the identity
    fields we require (id + source_file)."""
    node_id = node.get("id")
    source_file = node.get("source_file")
    if not node_id or not source_file:
        return None
    return {
        "folder_id": folder_id,
        "user_id": user_id,
        "node_id": str(node_id),
        "symbol": str(node.get("label") or node_id),
        "kind": infer_kind(node),
        "file": str(source_file),
        "start_line": parse_line(node.get("source_location")),
        "origin": node.get("_origin"),
    }


def map_edge(edge: dict, *, folder_id: str, user_id: str) -> dict | None:
    """Graphify link -> repo_edges row. Returns None if it lacks endpoints."""
    src = edge.get("source")
    dst = edge.get("target")
    relation = edge.get("relation")
    if not src or not dst or not relation:
        return None
    return {
        "folder_id": folder_id,
        "user_id": user_id,
        "src_node_id": str(src),
        "dst_node_id": str(dst),
        "relation": str(relation),
        "confidence": edge.get("confidence"),
        # An edge is OWNED by the file the reference appears in (its source_file).
        "ref_file": edge.get("source_file"),
        "ref_line": parse_line(edge.get("source_location")),
    }


def files_from_nodes(nodes: list[dict]) -> set[str]:
    """The set of source_files present in a batch of raw nodes."""
    return {str(n["source_file"]) for n in nodes if n.get("source_file")}
