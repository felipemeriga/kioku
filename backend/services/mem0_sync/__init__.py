"""Mem0 integration — thin proxy layer.

Mem0 is the source of truth for episodic + eternal memory. This package:
- Talks to the self-hosted kioku mem0 service over HTTP (one client per repo folder).
- Enforces our memory schema (scope, category, folder_id in metadata).
- Provides a fan-out helper that combines Mem0 with local RAG search.

Memory lives in the self-hosted service (Postgres/pgvector), not the hosted
Mem0 platform. Every read hits the service live.
"""

from .client import Mem0AppClient, MemoryScope, get_client_for_folder
from .schema import (
    CATEGORY_TAGS,
    EPISODIC_SCOPE,
    ETERNAL_SCOPE,
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
