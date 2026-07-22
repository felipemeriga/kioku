"""Per-repo code graph: symbol + reference index queried via MCP instead of
grep. Client-side extraction (Graphify/tree-sitter) uploads per-file deltas;
this package maps the raw graph into rows and merges/queries them in Postgres.
"""

from services.repo_graph.mapping import map_edge, map_node, parse_line
from services.repo_graph.store import (
    apply_delta,
    find_definition,
    find_references,
    impact_of,
    outline,
)

__all__ = [
    "map_node",
    "map_edge",
    "parse_line",
    "apply_delta",
    "find_definition",
    "find_references",
    "outline",
    "impact_of",
]
