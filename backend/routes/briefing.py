"""REST edit endpoints for the folder briefing (Phase 3).

Complements the MCP tools (get_folder_briefing_schema, get_folder_briefing,
update_folder_briefing_section) with equivalent HTTP routes so the UI's
per-section editor and the Suggest-from-repo button can drive the same
storage.

Section update semantics:
    - Setting content marks the section pinned + records provenance
      ('user_ui' from these routes, 'agent_mcp' from MCP tools).
    - Reset endpoint clears pinning so the next auto-regen fills the
      section from the mechanical populator (or LLM populator in
      Phase 4).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from db.client import get_supabase
from services.folder_summary.briefing_schema import (
    BRIEFING_SCHEMA_VERSION,
    SECTION_KEYS,
    empty_briefing,
    new_section,
)
from services.folder_summary.repo import get_folder, get_latest_summary

router = APIRouter(prefix="/api/folders")


import re as _re

_UUID_RE = _re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    _re.IGNORECASE,
)


def _folder_must_be_repo(sb, folder_id: str, user_id: str) -> dict:
    if not _UUID_RE.match(folder_id):
        raise HTTPException(status_code=404, detail="Folder not found")
    folder = get_folder(sb, folder_id, user_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    if (folder.get("kind") or "folder") != "repo":
        raise HTTPException(
            status_code=400,
            detail="Briefings are only for repo folders. This folder is not a repo.",
        )
    return folder


def _current_briefing(sb, folder_id: str, user_id: str) -> dict:
    latest = get_latest_summary(sb, folder_id, user_id)
    sections = None
    if latest:
        sections = latest.get("sections")
        if not sections and (latest.get("content") or {}).get("sections"):
            # Compat: pre-migration rows stashed sections inside content.
            sections = (latest.get("content") or {}).get("sections")
    return sections or empty_briefing()


@router.get("/{folder_id}/briefing/schema")
async def briefing_schema():
    """Canonical shape. Static — the frontend + coding agent can cache it.

    Handed back as {section_key: {content_shape, notes}} so a coding
    agent has enough context to fill any section correctly.
    """
    # Deliberately hand-crafted rather than derived from Pydantic — the
    # shape is small enough that hand-authored docstrings are worth more
    # to a coding agent than reflected types.
    return {
        "version": BRIEFING_SCHEMA_VERSION,
        "sections": {
            "overview": {
                "shape": {"purpose": "str", "description": "str"},
                "notes": "One sentence + a 2-4 sentence what/why.",
            },
            "architecture": {
                "shape": {
                    "summary": "str",
                    "components": [{"name": "str", "role": "str", "path": "str"}],
                    "data_flow": "str",
                },
                "notes": "How the system fits together — subsystems, boundaries, data flow.",
            },
            "preferences": {
                "shape": {"rules": ["str"]},
                "notes": "Auto-populated from Mem0 [preference]. Don't manually edit unless you want to override.",
            },
            "important_files": {
                "shape": [{"path": "str", "role": "str", "why": "str"}],
                "notes": "3-8 files an agent would want to open first.",
            },
            "how_it_runs": {
                "shape": {"requirements": ["str"], "local_dev": "str (multi-line ok)"},
                "notes": "Requirements list + local dev setup commands.",
            },
            "deployment": {
                "shape": {
                    "environments": ["str"],
                    "how_to_deploy": "str",
                    "ci_cd_notes": "str",
                },
                "notes": "Where it runs in production + how deploys happen.",
            },
            "dependencies": {
                "shape": {"runtime": ["str"], "services": ["str"]},
                "notes": "Auto-populated from manifests. Runtime deps + external services.",
            },
            "activity": {
                "shape": {
                    "recent_commits": ["{...}"],
                    "recent_prs": ["{...}"],
                    "recent_learnings": ["{...}"],
                },
                "notes": "Live git activity from the local clone (CLI-injected) + Mem0. Don't pin — it goes stale.",
            },
        },
    }


@router.get("/{folder_id}/briefing")
async def read_briefing(folder_id: str, user_id: str = Depends(get_current_user)):
    """Full current briefing state. Non-repo folders return 400."""
    sb = get_supabase()
    folder = _folder_must_be_repo(sb, folder_id, user_id)
    sections = _current_briefing(sb, folder_id, user_id)
    latest = get_latest_summary(sb, folder_id, user_id)
    return {
        "folder": folder,
        "schema_version": BRIEFING_SCHEMA_VERSION,
        "sections": sections,
        "last_generated_at": (latest or {}).get("generated_at"),
    }


class UpdateSectionRequest(BaseModel):
    content: Any  # section-shape depends on section; validated softly
    status: str = "pinned"  # 'pinned' | 'auto' | 'hybrid'
    updated_by: str | None = None  # free-form label


class ReplaceBriefingRequest(BaseModel):
    """Replace one or more sections in a single call.

    - `sections` is the desired shape. Missing keys are left alone
      (a partial replace is treated as a merge).
    - `pin_all` marks every provided section as pinned (default True),
      so auto-regen respects the caller's overwrite.
    """
    sections: dict[str, Any] = Field(default_factory=dict)
    pin_all: bool = True
    updated_by: str | None = None


@router.put("/{folder_id}/briefing")
async def replace_briefing(
    folder_id: str,
    body: ReplaceBriefingRequest,
    user_id: str = Depends(get_current_user),
):
    """Overwrite all provided sections in one atomic call.

    Rejects unknown section names with a helpful error. Sections not
    provided are preserved from the current state (partial replace ==
    merge). Every provided section is stamped provenance='user_ui'.
    """
    sb = get_supabase()
    _folder_must_be_repo(sb, folder_id, user_id)

    unknown = [k for k in body.sections.keys() if k not in SECTION_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown sections: {unknown}. Valid: {SECTION_KEYS}. "
                "Call the get_folder_briefing_schema tool for shape hints."
            ),
        )

    sections = _current_briefing(sb, folder_id, user_id)
    for key, content in body.sections.items():
        sections[key] = new_section(
            content,
            status="pinned" if body.pin_all else "auto",
            provenance="user_ui",
            updated_by=body.updated_by,
        )
    _persist_sections(sb, folder_id=folder_id, user_id=user_id, sections=sections)
    return {
        "ok": True,
        "replaced_sections": list(body.sections.keys()),
        "total_sections": len(sections),
    }


@router.patch("/{folder_id}/briefing/section/{section_name}")
async def update_briefing_section(
    folder_id: str,
    section_name: str,
    body: UpdateSectionRequest,
    user_id: str = Depends(get_current_user),
):
    """Patch one section. Marks it pinned by default so auto-regen respects it."""
    if section_name not in SECTION_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown section '{section_name}'. Valid: {SECTION_KEYS}",
        )
    if body.status not in ("auto", "pinned", "hybrid"):
        raise HTTPException(status_code=400, detail="status must be auto|pinned|hybrid")
    sb = get_supabase()
    _folder_must_be_repo(sb, folder_id, user_id)
    sections = _current_briefing(sb, folder_id, user_id)
    sections[section_name] = new_section(
        body.content,
        status=body.status,  # type: ignore[arg-type]
        provenance="user_ui",
        updated_by=body.updated_by,
    )
    _persist_sections(sb, folder_id=folder_id, user_id=user_id, sections=sections)
    return {"ok": True, "section": sections[section_name]}


def _persist_sections(
    sb, *, folder_id: str, user_id: str, sections: dict
) -> None:
    """Insert a new briefing row with the given sections map. We insert
    a fresh row on every edit so the history endpoint keeps its audit
    trail; the frontend always reads via get_latest_summary.

    Migration-safe: sequentially tries relaxed schema → downgraded kind
    → downgraded trigger, so pre-migration databases still persist.
    """
    payload = {
        "folder_id": folder_id,
        "user_id": user_id,
        "kind": "briefing",
        "trigger": "edit",
        "content": {"__briefing_v": BRIEFING_SCHEMA_VERSION, "sections": sections},
        "previous_content": None,
        "included_hashes": [],
        "doc_count": 0,
        "changed_files": {},
        "input_tokens": 0,
        "output_tokens": 0,
        "duration_ms": 0,
        "briefing_schema_version": BRIEFING_SCHEMA_VERSION,
        "sections": sections,
    }
    _insert_with_fallbacks(sb, payload)


def _insert_with_fallbacks(sb, payload: dict) -> None:
    """Persist a folder_summaries row, downgrading schema on each
    known constraint mismatch until it lands. Order:
      1. As-is (full new schema)
      2. Downgrade kind='briefing' → 'full' if kind_check rejects
      3. Downgrade trigger to 'manual' if trigger_check rejects
      4. Drop new columns if they don't exist yet
    """
    attempt = dict(payload)
    for _ in range(4):
        try:
            sb.table("folder_summaries").insert(attempt).execute()
            return
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            downgraded = False
            if "kind_check" in msg and attempt.get("kind") != "full":
                attempt["kind"] = "full"
                downgraded = True
            if "trigger_check" in msg and attempt.get("trigger") != "manual":
                attempt["trigger"] = "manual"
                downgraded = True
            if ("briefing_schema_version" in msg or "sections" in msg) \
                    and "briefing_schema_version" in attempt:
                attempt.pop("briefing_schema_version", None)
                attempt.pop("sections", None)
                downgraded = True
            if not downgraded:
                raise
    raise RuntimeError(
        "briefing persistence exhausted downgrade attempts; "
        "last error surfaced from Postgrest"
    )
