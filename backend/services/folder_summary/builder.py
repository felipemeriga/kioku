"""Orchestrates full and delta folder-summary generation.

Design:
- We reconstruct doc-level content by concatenating chunks per source_filename.
- Every doc gets a compact JSON summary (parallel Haiku calls).
- Full path: rollup all doc summaries into a folder summary.
- Delta path: previous summary + only the changed docs' summaries + removed list.
- Auto path: no previous → full, no changes → skip, otherwise → delta.

The heavy work runs inside asyncio.to_thread to keep the sync Anthropic client
happy inside an async arq task.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

from services.llm import Task, complete

from .diff import Diff, compute_diff
from .prompts import (
    DELTA_ROLLUP_SYSTEM,
    DELTA_ROLLUP_TOOL,
    DOC_SUMMARY_SYSTEM,
    DOC_SUMMARY_TOOL,
    FULL_ROLLUP_SYSTEM,
    FULL_ROLLUP_TOOL,
    build_delta_rollup_message,
    build_doc_summary_message,
    build_full_rollup_message,
)
from .repo import (
    get_docs_in_subtree,
    get_folder,
    get_folder_path,
    get_latest_summary,
    insert_summary,
)

log = logging.getLogger(__name__)


# Cap concurrent Anthropic doc-summary calls so a big folder doesn't blast the API.
DOC_SUMMARY_CONCURRENCY = 10
DOC_SUMMARY_MAX_TOKENS = 500
ROLLUP_MAX_TOKENS = 2000


class SummaryOutcome:
    __slots__ = ("kind", "row", "diff", "skipped_reason")

    def __init__(
        self,
        kind: str,
        row: dict | None,
        diff: Diff,
        skipped_reason: str | None = None,
    ):
        self.kind = kind
        self.row = row
        self.diff = diff
        self.skipped_reason = skipped_reason


def _extract_tool_input(msg, tool_name: str) -> dict:
    """Pull the tool-use block matching tool_name from a Message. Raises if absent."""
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return dict(block.input)
    raise RuntimeError(f"Model did not call tool {tool_name!r}. Content: {msg.content}")


# Anthropic tool-use JSON schema is advisory, not strict — Haiku can occasionally
# collapse an array into a single string with `<item>...</item>` XML-ish tags,
# especially on the delta path where it echoes the previous summary's shape.
# We coerce those rows before persisting so the UI (and downstream MCP consumers)
# always sees the declared shape.

_ITEM_RE = re.compile(r"<item[^>]*>(.*?)</item>", re.DOTALL | re.IGNORECASE)


def _coerce_string_to_list(value: str) -> list[str]:
    """Convert an XML-tagged or newline-separated string into a list of strings."""
    matches = _ITEM_RE.findall(value)
    if matches:
        return [m.strip() for m in matches if m.strip()]
    # Fall back to bullet/newline splitting.
    lines = [line.strip(" -*•\t") for line in value.splitlines() if line.strip()]
    return [line for line in lines if line]


def _normalize_folder_summary(payload: dict) -> dict:
    """Coerce every declared-array field into a real array.

    Guarantees the persisted summary matches the FolderSummary contract even
    when the model returns a stringified list. Any unrecoverable field becomes
    an empty list rather than a crash-inducing wrong type.
    """
    array_fields = ("themes", "key_documents", "key_facts", "entities", "gotchas")
    for field in array_fields:
        v = payload.get(field)
        if v is None:
            payload[field] = []
            continue
        if isinstance(v, list):
            continue
        if isinstance(v, str):
            payload[field] = _coerce_string_to_list(v)
            continue
        # dict or anything else — wrap so downstream never explodes
        payload[field] = []

    # themes/key_documents items must be objects, not bare strings
    payload["themes"] = [
        t if isinstance(t, dict) else {"name": str(t), "description": ""}
        for t in payload["themes"]
    ]
    payload["key_documents"] = [
        d if isinstance(d, dict) else {"filename": str(d), "role": ""}
        for d in payload["key_documents"]
    ]
    return payload


def _tokens(msg) -> tuple[int, int]:
    u = getattr(msg, "usage", None)
    if not u:
        return 0, 0
    return int(getattr(u, "input_tokens", 0) or 0), int(getattr(u, "output_tokens", 0) or 0)


def _summarize_document_sync(filename: str, content: str) -> tuple[dict, int, int]:
    msg = complete(
        task=Task.FOLDER_SUMMARY_DOC,
        system=DOC_SUMMARY_SYSTEM,
        messages=build_doc_summary_message(filename, content),
        tools=[DOC_SUMMARY_TOOL],
        max_tokens=DOC_SUMMARY_MAX_TOKENS,
    )
    payload = _extract_tool_input(msg, "emit_document_summary")
    payload["filename"] = filename
    it, ot = _tokens(msg)
    return payload, it, ot


async def _summarize_documents(docs: list[dict]) -> tuple[list[dict], int, int]:
    """Fan-out doc summaries with a bounded semaphore."""
    sem = asyncio.Semaphore(DOC_SUMMARY_CONCURRENCY)
    input_tokens = 0
    output_tokens = 0
    results: list[dict] = []

    async def one(doc: dict) -> dict | None:
        nonlocal input_tokens, output_tokens
        async with sem:
            try:
                payload, it, ot = await asyncio.to_thread(
                    _summarize_document_sync, doc["source_filename"], doc["content"]
                )
                input_tokens += it
                output_tokens += ot
                return payload
            except Exception as e:
                log.exception("doc-summary failed for %s: %s", doc["source_filename"], e)
                return None

    results = await asyncio.gather(*(one(d) for d in docs))
    return [r for r in results if r], input_tokens, output_tokens


def _run_full_rollup_sync(
    folder_name: str, folder_path: str, doc_summaries: list[dict]
) -> tuple[dict, int, int]:
    msg = complete(
        task=Task.FOLDER_SUMMARY_ROLLUP,
        system=FULL_ROLLUP_SYSTEM,
        messages=build_full_rollup_message(folder_name, folder_path, doc_summaries),
        tools=[FULL_ROLLUP_TOOL],
        max_tokens=ROLLUP_MAX_TOKENS,
    )
    payload = _normalize_folder_summary(_extract_tool_input(msg, "emit_folder_summary"))
    it, ot = _tokens(msg)
    return payload, it, ot


def _run_delta_rollup_sync(
    folder_name: str,
    folder_path: str,
    previous_summary: dict,
    added_summaries: list[dict],
    modified_summaries: list[dict],
    removed_filenames: list[str],
) -> tuple[dict, int, int]:
    msg = complete(
        task=Task.FOLDER_SUMMARY_ROLLUP,
        system=DELTA_ROLLUP_SYSTEM,
        messages=build_delta_rollup_message(
            folder_name,
            folder_path,
            previous_summary,
            added_summaries,
            modified_summaries,
            removed_filenames,
        ),
        tools=[DELTA_ROLLUP_TOOL],
        max_tokens=ROLLUP_MAX_TOKENS,
    )
    payload = _normalize_folder_summary(_extract_tool_input(msg, "emit_folder_summary"))
    it, ot = _tokens(msg)
    return payload, it, ot


def _decide_mode(
    requested: str, has_previous: bool, diff: Diff, force_full_if_delta_deep: bool = True
) -> str:
    """Resolve the mode: 'skip' | 'full' | 'delta'."""
    if requested == "full":
        return "full"
    if requested == "delta":
        return "delta" if has_previous else "full"
    # auto:
    if not has_previous:
        return "full"
    if diff.is_empty:
        return "skip"
    # A big-percentage change is better rebuilt from scratch than patched.
    if force_full_if_delta_deep and diff.count >= 20:
        return "full"
    return "delta"


async def generate_folder_summary(
    sb,
    *,
    folder_id: str,
    user_id: str,
    mode: str = "auto",
    trigger: str = "manual",
) -> SummaryOutcome:
    """Public entry point. Returns SummaryOutcome describing what happened.

    mode: 'auto' | 'full' | 'delta'
    trigger: freeform label persisted for observability ('manual', 'cron_nightly', 'cron_weekly').
    """
    assert mode in {"auto", "full", "delta"}, f"bad mode {mode!r}"
    started = time.perf_counter()

    folder = get_folder(sb, folder_id, user_id)
    if not folder:
        raise ValueError(f"folder {folder_id} not found for user {user_id}")
    folder_name = folder["name"]
    folder_path = get_folder_path(sb, folder_id, user_id) or folder_name

    # Container folders (e.g. 'cosm' which is just a bucket for c360-lead/,
    # h265/, nba/, smt/, Tiled Media/) get a workspace rollup instead of a
    # leaf summary. Detection: has subfolders AND ≤2 direct docs. The
    # rollup synthesizes the workspace briefing from the direct children's
    # own summaries.
    from services.folder_summary.repo import is_container_folder  # local: cycle-free
    if is_container_folder(sb, folder_id, user_id):
        from services.folder_summary.rollup import generate_workspace_rollup
        return await generate_workspace_rollup(
            sb, folder_id=folder_id, user_id=user_id, mode=mode, trigger=trigger,
        )

    docs = get_docs_in_subtree(sb, folder_id, user_id)
    current_manifest = [{"filename": d["source_filename"], "hash": d["content_hash"]} for d in docs]

    latest = get_latest_summary(sb, folder_id, user_id)
    previous_manifest = latest["included_hashes"] if latest else None
    if previous_manifest is not None and isinstance(previous_manifest, list) is False:
        # jsonb read back as dict/other — treat as absent to be safe
        previous_manifest = None

    diff = compute_diff(current_manifest, previous_manifest)
    resolved_mode = _decide_mode(mode, latest is not None, diff)

    log.info(
        "folder_summary: folder=%s docs=%d diff=+%d/-%d/~%d mode=%s (requested=%s)",
        folder_path or folder_name,
        len(docs),
        len(diff.added),
        len(diff.removed),
        len(diff.modified),
        resolved_mode,
        mode,
    )

    if resolved_mode == "skip":
        return SummaryOutcome(
            kind="skip", row=None, diff=diff, skipped_reason="no changes since last summary"
        )

    if not docs and resolved_mode == "full":
        # Empty folder — write a seed row so the UI knows the state was checked.
        seed_summary: dict[str, Any] = {
            "title": folder_name,
            "purpose": "This folder is empty.",
            "overview": "No documents have been added to this folder yet.",
            "themes": [],
            "key_documents": [],
            "key_facts": [],
            "entities": [],
            "gotchas": [],
        }
        row = insert_summary(
            sb,
            folder_id=folder_id,
            user_id=user_id,
            kind="seed",
            trigger=trigger,
            content=seed_summary,
            previous_content=(latest or {}).get("content"),
            included_hashes=current_manifest,
            doc_count=0,
            changed_files={"added": diff.added, "removed": diff.removed, "modified": diff.modified},
            input_tokens=0,
            output_tokens=0,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return SummaryOutcome(kind="seed", row=row, diff=diff)

    input_tokens = 0
    output_tokens = 0

    if resolved_mode == "full":
        doc_summaries, it, ot = await _summarize_documents(docs)
        input_tokens += it
        output_tokens += ot
        rollup, it, ot = await asyncio.to_thread(
            _run_full_rollup_sync, folder_name, folder_path, doc_summaries
        )
        input_tokens += it
        output_tokens += ot
    else:  # delta
        changed_filenames = set(diff.added) | set(diff.modified)
        changed_docs = [d for d in docs if d["source_filename"] in changed_filenames]
        change_summaries, it, ot = await _summarize_documents(changed_docs)
        input_tokens += it
        output_tokens += ot
        by_name = {s["filename"]: s for s in change_summaries}
        added_summaries = [by_name[n] for n in diff.added if n in by_name]
        modified_summaries = [by_name[n] for n in diff.modified if n in by_name]
        rollup, it, ot = await asyncio.to_thread(
            _run_delta_rollup_sync,
            folder_name,
            folder_path,
            (latest or {}).get("content") or {},
            added_summaries,
            modified_summaries,
            diff.removed,
        )
        input_tokens += it
        output_tokens += ot

    row = insert_summary(
        sb,
        folder_id=folder_id,
        user_id=user_id,
        kind=resolved_mode,
        trigger=trigger,
        content=rollup,
        previous_content=(latest or {}).get("content"),
        included_hashes=current_manifest,
        doc_count=len(docs),
        changed_files={"added": diff.added, "removed": diff.removed, "modified": diff.modified},
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return SummaryOutcome(kind=resolved_mode, row=row, diff=diff)
