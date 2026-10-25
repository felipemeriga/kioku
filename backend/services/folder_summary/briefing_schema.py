"""Pure-schema helpers for the folder briefing — no github_sync dependency.

These are the building blocks that the KEEP path (`replace_briefing`,
`_persist_sections`) and any future code imports without needing the
repo-generation machinery.

Deliberately thin:  no I/O, no DB, no LLM, no local-clone logic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

BRIEFING_SCHEMA_VERSION = 2

SectionStatus = Literal["auto", "pinned", "hybrid"]
Provenance = Literal["auto", "user_ui", "agent_mcp"]


# ── Section keys — fixed order for stable rendering ────────────────────────
SECTION_KEYS: list[str] = [
    "overview",
    "architecture",
    "preferences",
    "how_it_runs",
    "deployment",
    "activity",
    "documentation",
]


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def new_section(
    content: Any,
    *,
    status: SectionStatus = "auto",
    provenance: Provenance = "auto",
    updated_by: str | None = None,
) -> dict:
    return {
        "status": status,
        "content": content,
        "provenance": provenance,
        "updated_at": _now_iso(),
        "updated_by": updated_by,
    }


def empty_briefing() -> dict[str, dict]:
    """Skeleton briefing with every section marked auto + empty. Used as
    the base when a new repo hasn't had any populators run yet."""
    return {
        "overview": new_section({"purpose": "", "description": ""}),
        "architecture": new_section(
            {
                "summary": "",
                "components": [],
                "data_flow": "",
            }
        ),
        "preferences": new_section({"rules": []}),
        "how_it_runs": new_section(
            {
                "requirements": [],
                "local_dev": "",
            }
        ),
        "deployment": new_section(
            {
                "environments": [],
                "how_to_deploy": "",
                "ci_cd_notes": "",
            }
        ),
        "activity": new_section(
            {
                "summary": "",
                "highlights": [],
            }
        ),
        "documentation": new_section(""),
    }


def merge_briefing(*, existing: dict | None, refresh: dict) -> dict:
    """Return a new briefing where each section is either the pinned
    existing section (untouched) or the refreshed auto section.

    `existing` may be None on first population. Missing sections in
    either input use the empty skeleton so the shape is stable."""
    base = existing or empty_briefing()
    out: dict[str, dict] = {}
    for key in SECTION_KEYS:
        e = base.get(key)
        r = refresh.get(key)
        if e and (e.get("status") in ("pinned", "hybrid")):
            # Keep the user/agent's edit.
            out[key] = e
            continue
        # Fall back to the refresh; if refresh missing the key, keep empty.
        out[key] = r or e or empty_briefing()[key]
    return out


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def snapshot_sections(row: dict | None) -> dict:
    """Read current content after Mihari's atomic jsonb section updates.

    Top-level sections are a fallback for older rows; Mihari updates
    content.sections in place without rewriting that top-level column.
    """
    row = row or {}
    merged = {**(row.get("sections") or {}), **((row.get("content") or {}).get("sections") or {})}
    return {key: merged[key] for key in SECTION_KEYS if key in merged}


def briefing_content_hash(sections: dict) -> str:
    """sha256 of the sections CONTENT only (metadata excluded), canonical + stable."""
    content = {k: (sections.get(k) or {}).get("content") for k in SECTION_KEYS}
    return hashlib.sha256(_canonical(content).encode()).hexdigest()


def _is_empty(content: Any) -> bool:
    return content in (None, "", [], {}) or (
        isinstance(content, dict) and all(_is_empty(v) for v in content.values())
    )


def changed_sections(prev: dict | None, cur: dict) -> list[str]:
    """Section keys whose content differs between two briefings. prev=None ->
    every key whose content is non-empty."""
    out: list[str] = []
    for k in SECTION_KEYS:
        cur_c = (cur.get(k) or {}).get("content")
        if prev is None:
            if not _is_empty(cur_c):
                out.append(k)
            continue
        prev_c = (prev.get(k) or {}).get("content")
        if _canonical(prev_c) != _canonical(cur_c):
            out.append(k)
    return out
