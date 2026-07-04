"""The standard memory schema agentic-rag enforces on top of Mem0.

Every memory written through our proxy carries this metadata so retrieval
can be scoped, filtered, and audited consistently:

  metadata = {
      "folder_id": "<uuid>",          # scope to a folder tree
      "scope":     "eternal|episodic", # policy vs. history
      "category":  "decision|finding|issue|preference|session|note",
      "tags":      ["repo=x", "backend", "auth"],  # freeform
      "written_by": "claude-code|user|system",
  }

Eternal memories are always inlined in orientation payloads (session-start).
Episodic memories require semantic search to surface.
"""

from __future__ import annotations

from typing import Literal, TypedDict

ETERNAL_SCOPE = "eternal"
EPISODIC_SCOPE = "episodic"

MemoryScopeLiteral = Literal["eternal", "episodic"]

MemoryCategoryLiteral = Literal[
    "decision", "finding", "issue", "preference", "session", "note"
]


class MemoryCategory:
    DECISION = "decision"
    FINDING = "finding"
    ISSUE = "issue"
    PREFERENCE = "preference"
    SESSION = "session"
    NOTE = "note"

    @classmethod
    def all(cls) -> tuple[str, ...]:
        return (cls.DECISION, cls.FINDING, cls.ISSUE, cls.PREFERENCE, cls.SESSION, cls.NOTE)


# Category-to-canonical-tag mapping (matches the user's existing memory format,
# e.g. `[decision] repo=x ...`).
CATEGORY_TAGS = {
    MemoryCategory.DECISION: "[decision]",
    MemoryCategory.FINDING: "[finding]",
    MemoryCategory.ISSUE: "[issue]",
    MemoryCategory.PREFERENCE: "[preference]",
    MemoryCategory.SESSION: "[session]",
    MemoryCategory.NOTE: "[note]",
}


class MemoryRecord(TypedDict, total=False):
    id: str
    memory: str
    metadata: dict
    categories: list[str]
    created_at: str
    updated_at: str
    score: float


def build_metadata(
    *,
    folder_id: str,
    scope: str = EPISODIC_SCOPE,
    category: str = MemoryCategory.NOTE,
    tags: list[str] | None = None,
    written_by: str = "claude-code",
    extra: dict | None = None,
) -> dict:
    """Compose the canonical metadata blob for a memory write.

    Callers pass domain fields; we shape them into the exact structure the
    fan-out layer expects to filter on later.
    """
    scope = scope if scope in (ETERNAL_SCOPE, EPISODIC_SCOPE) else EPISODIC_SCOPE
    category = category if category in MemoryCategory.all() else MemoryCategory.NOTE
    md: dict = {
        "folder_id": folder_id,
        "scope": scope,
        "category": category,
        "tags": list(tags or []),
        "written_by": written_by,
    }
    if extra:
        md.update(extra)
    return md
