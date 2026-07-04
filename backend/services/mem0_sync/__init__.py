"""Mem0 integration — thin proxy layer.

Mem0 is the source of truth for episodic + eternal memory. This package:
- Wraps the Mem0 cloud SDK behind a config-per-folder pattern.
- Enforces our memory schema (scope, category, folder_id in metadata).
- Provides a fan-out helper that combines Mem0 with local RAG search.

We do NOT mirror Mem0 into Postgres. Every read hits Mem0 live.
"""

from .client import Mem0AppClient, MemoryScope, get_client_for_folder
from .schema import (
    CATEGORY_TAGS,
    ETERNAL_SCOPE,
    EPISODIC_SCOPE,
    MemoryCategory,
    MemoryRecord,
    build_metadata,
)

__all__ = [
    "CATEGORY_TAGS",
    "EPISODIC_SCOPE",
    "ETERNAL_SCOPE",
    "Mem0AppClient",
    "MemoryCategory",
    "MemoryRecord",
    "MemoryScope",
    "build_metadata",
    "get_client_for_folder",
]
