"""The standard memory schema agentic-rag enforces on top of Mem0.

Every memory written through our proxy carries this metadata so retrieval
can be scoped, filtered, and audited consistently:

  metadata = {
      "folder_id":  "<uuid>",          # scope to a folder tree
      "scope":      "eternal|episodic", # policy vs. history
      "category":   "decision|finding|issue|preference|session|note",
      "tags":       ["repo=x", "backend", "auth"],  # freeform
      "written_by": "claude-code|user|system",
      "dedup_key":  "<sha256>",        # deterministic id for exact-match dedup
  }

Eternal memories are always inlined in orientation payloads (session-start).
Episodic memories require semantic search to surface.
"""

from __future__ import annotations

import hashlib
import re
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


_WS_RE = re.compile(r"\s+")


def normalize_content(content: str) -> str:
    """Canonical form used for the dedup hash.

    Lowercase, collapse whitespace, strip leading/trailing punctuation.
    Two writes that differ only in trailing period or double-space now
    collide on the same dedup_key.
    """
    if not content:
        return ""
    lowered = content.strip().lower()
    collapsed = _WS_RE.sub(" ", lowered)
    return collapsed.rstrip(".!?;:,)]}\"'` ").lstrip("([{\"'` ")


def compute_content_hash(*, content: str, folder_id: str) -> str:
    """Content-only identity. Matches Mem0's own dedup behavior: the same
    text in the same folder is the same memory, regardless of scope/category."""
    return hashlib.sha256(
        f"{folder_id}|{normalize_content(content)}".encode("utf-8")
    ).hexdigest()


def compute_dedup_key(
    *, content: str, folder_id: str, scope: str, category: str
) -> str:
    """Categorical identity: same content + same scope + same category. Kept
    alongside content_hash for observability, but content_hash is the
    load-bearing lookup because Mem0 itself keys on content."""
    canonical = normalize_content(content)
    payload = f"{folder_id}|{scope}|{category}|{canonical}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_metadata(
    *,
    folder_id: str,
    scope: str = EPISODIC_SCOPE,
    category: str = MemoryCategory.NOTE,
    tags: list[str] | None = None,
    written_by: str = "claude-code",
    content: str = "",
    extra: dict | None = None,
) -> dict:
    """Compose the canonical metadata blob for a memory write.

    Callers pass domain fields; we shape them into the exact structure the
    fan-out layer expects to filter on later. dedup_key is computed here so
    every write path uses the same recipe.
    """
    scope = scope if scope in (ETERNAL_SCOPE, EPISODIC_SCOPE) else EPISODIC_SCOPE
    category = category if category in MemoryCategory.all() else MemoryCategory.NOTE
    md: dict = {
        "folder_id": folder_id,
        "scope": scope,
        "category": category,
        "tags": list(tags or []),
        "written_by": written_by,
        "content_hash": compute_content_hash(content=content, folder_id=folder_id),
        "dedup_key": compute_dedup_key(
            content=content, folder_id=folder_id, scope=scope, category=category
        ),
    }
    if extra:
        md.update(extra)
    return md
