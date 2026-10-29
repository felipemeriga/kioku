"""Validate and synchronize local agent journals without document ingestion."""

import hashlib
import json
import re
from datetime import date, datetime

from storage3.exceptions import StorageApiError

BUCKET = "agent-journals"
MAX_BYTES = 5 * 1024 * 1024
ENTRY_RE = re.compile(r"^<!-- kioku-entry: (\{[^\n]*\}) -->$", re.MULTILINE)
ALLOWED_AGENTS = {"claude_code", "codex"}
HEADING_RE = re.compile(r"^## (\d\d:\d\d) — [^\n]+\n", re.MULTILINE)


def journal_sessions(markdown: str) -> list[dict]:
    """Group a day's entries by native agent session, including legacy journals."""
    headings = list(HEADING_RE.finditer(markdown))
    sessions: dict[tuple[str, str], dict] = {}
    for index, heading in enumerate(headings):
        block = markdown[
            heading.end() : headings[index + 1].start()
            if index + 1 < len(headings)
            else len(markdown)
        ]
        marker = ENTRY_RE.search(block)
        if not marker:
            continue
        entry = json.loads(marker.group(1))
        agent, session_id = entry["agent"], entry["session_id"]
        key = (agent, session_id)
        prose = block[marker.end() :].strip()
        fallback = re.sub(r"^[#*\-\s]+", "", prose.splitlines()[0] if prose else "").strip()
        record = sessions.setdefault(
            key,
            {
                "agent": agent,
                "session_id": session_id,
                "title": fallback[:120] or "Untitled session",
                "summary": "",
                "computer_name": entry.get("computer_name") or "",
                "entry_count": 0,
                "first_time": heading.group(1),
                "last_time": heading.group(1),
            },
        )
        record["entry_count"] += 1
        record["last_time"] = heading.group(1)
        if entry.get("session_title"):
            record["title"] = entry["session_title"]
        if entry.get("session_summary"):
            record["summary"] = entry["session_summary"]
        if entry.get("computer_name"):
            record["computer_name"] = entry["computer_name"]
    return list(sessions.values())


def inspect_journal(markdown: str, journal_date: str) -> dict:
    """Return index metadata; reject malformed or mismatched daily files."""
    try:
        day = date.fromisoformat(journal_date)
    except ValueError as exc:
        raise ValueError("Invalid journal date") from exc
    raw = markdown.encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValueError("Journal exceeds 5 MiB")
    if not markdown.startswith(f"# Kioku agent journal — {journal_date}\n"):
        raise ValueError("Journal header does not match date")
    if "\r" in markdown:
        raise ValueError("Journal must use LF line endings")

    entries = []
    seen = set()
    for match in ENTRY_RE.finditer(markdown):
        try:
            entry = json.loads(match.group(1))
            agent = entry["agent"]
            entry_id = entry["id"]
            captured_at = datetime.fromisoformat(entry["captured_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid journal entry metadata") from exc
        if agent not in ALLOWED_AGENTS or not isinstance(entry_id, str):
            raise ValueError("Invalid journal agent or entry ID")
        if entry_id in seen or captured_at.tzinfo is None or captured_at.date() != day:
            raise ValueError("Duplicate entry ID or timestamp outside journal date")
        if not isinstance(entry.get("session_id"), str) or not isinstance(
            entry.get("source_ref"), str
        ):
            raise ValueError("Missing session or source reference")
        for field, limit in (
            ("session_title", 120),
            ("session_summary", 800),
            ("computer_name", 120),
        ):
            value = entry.get(field)
            if value is not None and (
                not isinstance(value, str) or not value or len(value) > limit
            ):
                raise ValueError(f"Invalid {field}")
        seen.add(entry_id)
        entries.append((agent, captured_at))
    if not entries:
        raise ValueError("Journal has no entries")
    if markdown.count("<!-- kioku-entry:") != len(entries):
        raise ValueError("Malformed entry marker")
    timestamps = [ts for _, ts in entries]
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "entry_count": len(entries),
        "agents": sorted({agent for agent, _ in entries}),
        "first_entry_at": min(timestamps).isoformat(),
        "last_entry_at": max(timestamps).isoformat(),
    }


def read_journal(sb, user_id: str, folder_id: str, journal_date: str) -> dict:
    rows = (
        sb.table("agent_journal_days")
        .select("storage_path,content_sha256,revision")
        .eq("user_id", user_id)
        .eq("folder_id", folder_id)
        .eq("journal_date", journal_date)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return {"status": "absent", "revision": 0, "markdown": ""}
    row = rows[0]
    raw = sb.storage.from_(BUCKET).download(row["storage_path"])
    if hashlib.sha256(raw).hexdigest() != row["content_sha256"]:
        raise RuntimeError("Journal object does not match its index hash")
    markdown = raw.decode("utf-8")
    return {
        "status": "ok",
        "revision": row["revision"],
        "markdown": markdown,
        "sessions": journal_sessions(markdown),
    }


def sync_journal(
    sb,
    *,
    user_id: str,
    folder_id: str,
    journal_date: str,
    markdown: str,
    base_revision: int,
    content_sha256: str,
) -> dict:
    metadata = inspect_journal(markdown, journal_date)
    if metadata["sha256"] != content_sha256:
        raise ValueError("Journal checksum mismatch")
    if not isinstance(base_revision, int) or base_revision < 0:
        raise ValueError("Invalid base revision")
    current_rows = (
        sb.table("agent_journal_days")
        .select("content_sha256,revision,storage_path")
        .eq("user_id", user_id)
        .eq("folder_id", folder_id)
        .eq("journal_date", journal_date)
        .limit(1)
        .execute()
        .data
        or []
    )
    if current_rows and current_rows[0]["content_sha256"] == content_sha256:
        return {"status": "unchanged", "revision": current_rows[0]["revision"]}
    if (current_rows[0]["revision"] if current_rows else 0) != base_revision:
        return {"status": "conflict", "revision": current_rows[0]["revision"]}

    path = f"{user_id}/{folder_id}/{journal_date}/{content_sha256}.md"
    bucket = sb.storage.from_(BUCKET)
    try:
        bucket.upload(path, markdown.encode("utf-8"), {"content-type": "text/markdown"})
    except StorageApiError as exc:
        if str(exc.status) != "409":
            raise
        # Identical content-addressed object from a previous interrupted attempt.
    result = (
        sb.rpc(
            "publish_agent_journal",
            {
                "p_user_id": user_id,
                "p_folder_id": folder_id,
                "p_date": journal_date,
                "p_expected_revision": base_revision,
                "p_storage_path": path,
                "p_sha256": content_sha256,
                "p_entry_count": metadata["entry_count"],
                "p_agents": metadata["agents"],
                "p_first_entry_at": metadata["first_entry_at"],
                "p_last_entry_at": metadata["last_entry_at"],
            },
        )
        .execute()
        .data
    )
    if isinstance(result, list):
        result = result[0]
    if not isinstance(result, dict):
        raise RuntimeError("Journal publish returned no status")
    if result.get("status") == "conflict":
        try:
            bucket.remove([path])
        except Exception:
            pass  # A later storage cleanup can remove an orphaned object.
    old_path = result.get("previous_path")
    if result.get("status") == "ok" and old_path and old_path != path:
        try:
            bucket.remove([old_path])
        except Exception:
            # The indexed object is already authoritative. Old-object cleanup
            # is best effort and can be retried by a maintenance job later.
            pass
    return {"status": result["status"], "revision": result["revision"]}
