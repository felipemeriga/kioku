"""Shared append-only persistence for UI and MCP briefing snapshots."""

from .briefing_schema import BRIEFING_SCHEMA_VERSION, briefing_content_hash, snapshot_sections
from .repo import get_latest_summary


def persist_sections(
    sb, *, folder_id: str, user_id: str, sections: dict, trigger: str = "edit"
) -> dict | None:
    """Append changed briefing content; retain the latest row for no-op edits.

    Dedup gate: if the section *content* (metadata excluded) is identical
    to the latest stored version, the insert is skipped and the existing
    row is returned so callers can still reference it.

    Migration-safe: sequentially tries relaxed schema → downgraded kind
    → downgraded trigger, so pre-migration databases still persist.
    """
    new_hash = briefing_content_hash(sections)
    latest = get_latest_summary(sb, folder_id, user_id)
    if latest is not None:
        latest_hash = latest.get("content_hash")
        if not latest_hash:
            latest_sections = snapshot_sections(latest)
            latest_hash = briefing_content_hash(latest_sections)
        if latest_hash == new_hash:
            return latest  # identical content -> no new version

    payload = {
        "folder_id": folder_id,
        "user_id": user_id,
        "kind": "briefing",
        "trigger": trigger,
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
        "content_hash": new_hash,
    }
    _insert_with_fallbacks(sb, payload)
    return payload


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
            if (
                "briefing_schema_version" in msg or "sections" in msg
            ) and "briefing_schema_version" in attempt:
                attempt.pop("briefing_schema_version", None)
                attempt.pop("sections", None)
                downgraded = True
            if not downgraded:
                raise
    raise RuntimeError(
        "briefing persistence exhausted downgrade attempts; last error surfaced from Postgrest"
    )
