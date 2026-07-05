"""Workspace rollup — build a folder summary for a container folder by
synthesizing the summaries of its direct subfolders.

The container gets its OWN folder_summaries row with kind='workspace_rollup'.
The row stores a snapshot of the child summary IDs it was rolled up from —
`subfolder_snapshots: {child_folder_id: child_summary_id}` — so auto-mode
can detect staleness by comparing that map against the current latest
summary per child.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from services.folder_summary.builder import (
    SummaryOutcome,
    _extract_tool_input,
    _normalize_folder_summary,
    _tokens,
)
from services.folder_summary.prompts import (
    WORKSPACE_ROLLUP_SYSTEM,
    WORKSPACE_ROLLUP_TOOL,
    build_workspace_rollup_message,
)
from services.folder_summary.repo import (
    count_direct_docs,
    get_direct_subfolders,
    get_folder,
    get_folder_path,
    get_latest_summary,
    insert_summary,
)
from services.llm import Task, complete

log = logging.getLogger(__name__)

ROLLUP_MAX_TOKENS = 2000


@dataclass
class ChildBriefing:
    """One row in the LLM's input — a compact view of a direct child's summary."""

    folder_id: str
    folder_name: str
    summary_id: str | None  # id of the child's latest folder_summaries row
    content: dict  # the child's structured summary payload
    doc_count: int
    has_mem0: bool
    has_github: bool
    has_notion: bool


def _get_integration_flags(sb, folder_id: str, user_id: str) -> tuple[bool, bool, bool]:
    """Cheap: three HEAD counts to check config presence."""
    def _exists(table: str, col: str) -> bool:
        r = (
            sb.table(table).select("id", count="exact", head=True)
            .eq(col, folder_id).eq("user_id", user_id).execute()
        )
        return (r.count or 0) > 0
    return (
        _exists("mem0_sync_configs", "root_folder_id"),
        _exists("github_sync_configs", "root_folder_id"),
        _exists("notion_sync_configs", "root_folder_id"),
    )


def _gather_children(sb, folder_id: str, user_id: str) -> list[ChildBriefing]:
    """Build a ChildBriefing per direct subfolder.

    A child WITHOUT a summary yet still gets a briefing with an empty
    content dict — the LLM will just skip it. The caller (build_rollup)
    decides whether to pre-generate stale children before rolling up.
    """
    subs = get_direct_subfolders(sb, folder_id, user_id)
    briefings: list[ChildBriefing] = []
    for sub in subs:
        child_id = sub["id"]
        latest = get_latest_summary(sb, child_id, user_id)
        content = (latest or {}).get("content") or {}
        summary_id = (latest or {}).get("id")
        # doc_count directly on the child (not subtree — we already recurse).
        direct = count_direct_docs(sb, child_id, user_id)
        has_mem0, has_github, has_notion = _get_integration_flags(
            sb, child_id, user_id
        )
        briefings.append(
            ChildBriefing(
                folder_id=child_id,
                folder_name=sub["name"],
                summary_id=summary_id,
                content=content,
                doc_count=direct,
                has_mem0=has_mem0,
                has_github=has_github,
                has_notion=has_notion,
            )
        )
    return briefings


def _briefing_for_prompt(b: ChildBriefing) -> dict:
    """Trim a ChildBriefing down to the fields the LLM should see."""
    c = b.content or {}
    return {
        "name": b.folder_name,
        "purpose": c.get("purpose") or "",
        "overview": c.get("overview") or "",
        "key_facts": c.get("key_facts") or [],
        "themes": c.get("themes") or [],
        "gotchas": c.get("gotchas") or [],
        "doc_count": b.doc_count,
        "has_mem0": b.has_mem0,
        "has_github": b.has_github,
        "has_notion": b.has_notion,
    }


def _run_workspace_rollup_sync(
    folder_name: str,
    folder_path: str,
    child_briefings: list[dict],
) -> tuple[dict, int, int]:
    msg = complete(
        task=Task.FOLDER_SUMMARY_ROLLUP,
        system=WORKSPACE_ROLLUP_SYSTEM,
        messages=build_workspace_rollup_message(
            folder_name, folder_path, child_briefings, pooled_activity=None
        ),
        tools=[WORKSPACE_ROLLUP_TOOL],
        max_tokens=ROLLUP_MAX_TOKENS,
    )
    payload = _normalize_folder_summary(_extract_tool_input(msg, "emit_folder_summary"))
    it, ot = _tokens(msg)
    return payload, it, ot


async def generate_workspace_rollup(
    sb,
    *,
    folder_id: str,
    user_id: str,
    mode: str = "auto",
    trigger: str = "manual",
) -> SummaryOutcome:
    """Build a workspace_rollup summary for a container folder.

    Behavior by mode:
      - auto: skip if no direct child's summary has moved since the last
        rollup we produced. Otherwise regen.
      - full: always regen. Children are NOT force-regen'd (users can hit
        Full on children directly). This is the cheap-but-correct choice.
      - delta: same as auto for containers — the rollup is atomic. There's
        no meaningful patch-in-place at the workspace level.
    """
    from services.folder_summary.builder import generate_folder_summary  # local to break cycle

    started = time.perf_counter()

    folder = get_folder(sb, folder_id, user_id)
    if not folder:
        raise ValueError(f"folder {folder_id} not found for user {user_id}")
    folder_name = folder["name"]
    folder_path = get_folder_path(sb, folder_id, user_id) or folder_name

    # Ensure any child that has NEVER been summarized has one. Don't touch
    # children that already have a row — they're the child's own truth.
    subs = get_direct_subfolders(sb, folder_id, user_id)
    for sub in subs:
        latest = get_latest_summary(sb, sub["id"], user_id)
        if latest is None:
            log.info(
                "workspace_rollup: bootstrapping child summary for %s/%s",
                folder_name, sub["name"],
            )
            try:
                await generate_folder_summary(
                    sb, folder_id=sub["id"], user_id=user_id,
                    mode="full", trigger=f"rollup_bootstrap:{trigger}",
                )
            except Exception:  # noqa: BLE001
                log.exception(
                    "workspace_rollup: child bootstrap failed for %s; continuing",
                    sub["id"],
                )

    briefings = _gather_children(sb, folder_id, user_id)
    latest_parent = get_latest_summary(sb, folder_id, user_id)
    previous_snapshots = (latest_parent or {}).get("subfolder_snapshots") or {}
    current_snapshots = {b.folder_id: b.summary_id for b in briefings if b.summary_id}

    # auto/delta: skip if nothing has moved.
    if mode in ("auto", "delta") and latest_parent is not None:
        if current_snapshots == previous_snapshots:
            log.info(
                "workspace_rollup: skipping %s — no child summary changes since %s",
                folder_name, latest_parent.get("generated_at"),
            )
            return SummaryOutcome(
                kind="skip",
                row=None,
                diff=None,
                skipped_reason="no child summaries changed since last rollup",
            )

    if not briefings:
        # Container promise broken — no subfolders. Fall through to a seed
        # row so downstream doesn't see stale data.
        seed_summary: dict[str, Any] = {
            "title": folder_name,
            "purpose": "This folder is empty.",
            "overview": "No subfolders and no direct documents.",
            "themes": [],
            "key_documents": [],
            "key_facts": [],
            "entities": [],
            "gotchas": [],
        }
        row = insert_summary(
            sb,
            folder_id=folder_id, user_id=user_id,
            kind="seed", trigger=trigger,
            content=seed_summary,
            previous_content=(latest_parent or {}).get("content"),
            included_hashes=[],
            doc_count=0,
            changed_files={"added": [], "removed": [], "modified": []},
            input_tokens=0, output_tokens=0,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return SummaryOutcome(kind="seed", row=row, diff=None)

    log.info(
        "workspace_rollup: folder=%s children=%d mode=%s",
        folder_path or folder_name, len(briefings), mode,
    )

    prompt_briefings = [_briefing_for_prompt(b) for b in briefings]
    rollup, input_tokens, output_tokens = await asyncio.to_thread(
        _run_workspace_rollup_sync, folder_name, folder_path, prompt_briefings
    )

    # Persist. subfolder_snapshots goes in changed_files for compatibility
    # with the existing insert_summary shape until the new column ships
    # via migration; also passed via the new column path below.
    row = _insert_workspace_rollup(
        sb,
        folder_id=folder_id, user_id=user_id, trigger=trigger,
        content=rollup,
        previous_content=(latest_parent or {}).get("content"),
        subfolder_snapshots=current_snapshots,
        doc_count=sum(b.doc_count for b in briefings),
        subfolder_count=len(briefings),
        input_tokens=input_tokens, output_tokens=output_tokens,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return SummaryOutcome(kind="workspace_rollup", row=row, diff=None)


def _insert_workspace_rollup(
    sb,
    *,
    folder_id: str,
    user_id: str,
    trigger: str,
    content: dict,
    previous_content: dict | None,
    subfolder_snapshots: dict[str, str],
    doc_count: int,
    subfolder_count: int,
    input_tokens: int,
    output_tokens: int,
    duration_ms: int,
) -> dict:
    """Direct insert with the workspace_rollup kind. Kept separate from
    the leaf builder's insert_summary so we can set the new
    subfolder_snapshots column without altering the shared helper."""
    payload = {
        "folder_id": folder_id,
        "user_id": user_id,
        "kind": "workspace_rollup",
        "trigger": trigger,
        "content": content,
        "previous_content": previous_content,
        "included_hashes": [],  # not meaningful for rollups
        "doc_count": doc_count,
        "changed_files": {
            "subfolder_count": subfolder_count,
            # dupe-store snapshots inside changed_files so the row is still
            # informative even if the subfolder_snapshots column is missing
            # (fresh-clone databases before the migration lands).
            "subfolder_snapshots": subfolder_snapshots,
        },
        "subfolder_snapshots": subfolder_snapshots,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "duration_ms": duration_ms,
    }
    try:
        r = sb.table("folder_summaries").insert(payload).execute()
        return r.data[0]
    except Exception as exc:  # noqa: BLE001
        # Fallback for the transition window: if the DB schema hasn't been
        # migrated yet, retry without the new column.
        msg = str(exc)
        if "subfolder_snapshots" not in msg and "kind_check" not in msg:
            raise
        log.warning(
            "workspace_rollup insert falling back (migration not applied?): %s",
            msg,
        )
        payload.pop("subfolder_snapshots", None)
        # If the constraint blocks the new kind, downgrade to 'full'.
        if "kind_check" in msg:
            payload["kind"] = "full"
        r = sb.table("folder_summaries").insert(payload).execute()
        return r.data[0]


def build_workspace_orientation_payload(
    sb,
    *,
    folder_id: str,
    user_id: str,
    latest_row: dict,
) -> dict:
    """Assemble the payload the MCP orientation call returns for a container.

    Called by mcp_server.get_folder_orientation when it detects
    kind == 'workspace_rollup'. Returns a dict with:

      {folder, kind, summary, subfolders[], rules[], recent_activity, metadata}
    """
    briefings = _gather_children(sb, folder_id, user_id)
    subfolders_payload = [
        {
            "id": b.folder_id,
            "name": b.folder_name,
            "purpose": (b.content or {}).get("purpose") or "",
            "overview": (b.content or {}).get("overview") or "",
            "key_facts": (b.content or {}).get("key_facts") or [],
            "doc_count": b.doc_count,
            "has_mem0": b.has_mem0,
            "has_github": b.has_github,
            "has_notion": b.has_notion,
            "has_summary": bool(b.summary_id),
        }
        for b in briefings
    ]
    return {
        "kind": "workspace_rollup",
        "summary": latest_row.get("content") or {},
        "subfolders": subfolders_payload,
    }
