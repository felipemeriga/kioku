"""Indexed journal search; original transcript contents are intentionally excluded."""

import hashlib
import re
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.agent_journal import entry_instant, journal_entries, journal_sessions, read_journal


def search_entries(markdown: str) -> list[dict]:
    sessions = {(x["agent"], x["session_id"]): x for x in journal_sessions(markdown)}
    result = []
    for item in journal_entries(markdown):
        meta = item["metadata"]
        session = sessions[(meta["agent"], meta["session_id"])]
        # Exclude capture markers and generated timestamp headings from body matching.
        body = item["block"].split(" -->\n", 1)[-1].strip()
        result.append(
            {
                "entry_id": meta["id"],
                "agent": meta["agent"],
                "session_id": meta["session_id"],
                "captured_at": entry_instant(meta).isoformat(),
                "title": session["title"],
                "summary": session["summary"],
                "body": body,
            }
        )
    return result


def index_journal(sb, user_id: str, folder_id: str, journal_date: str, sha: str, markdown: str):
    return (
        sb.rpc(
            "index_agent_journal",
            {
                "p_user_id": user_id,
                "p_folder_id": folder_id,
                "p_date": journal_date,
                "p_sha256": sha,
                "p_entries": search_entries(markdown),
            },
        )
        .execute()
        .data
    )


def compile_pattern(query: str, mode: str) -> str:
    """Use PostgreSQL's non-backtracking regular subset, excluding backreferences.

    Groups/lookaround and counted/nested repetition are deliberately unavailable in
    user patterns. Literal modes escape every metacharacter, including backslashes.
    """
    if any(ord(char) < 32 or ord(char) == 127 for char in query):
        raise ValueError("Search must be a single line without control characters")
    if len(query) > 160:
        raise ValueError("Search is limited to 160 characters")
    if mode not in {"words", "phrase", "regex"}:
        raise ValueError("Invalid search mode")
    if not query.strip():
        return ""
    if mode == "phrase":
        return re.escape(query)
    if mode == "words":
        return "".join("(?=.*" + re.escape(word) + ")" for word in query.split()) + ".*"
    if any(c in query for c in "(){}") or re.search(r"\\[1-9]", query):
        raise ValueError(
            "Regex supports classes, anchors, alternatives and simple repetition; "
            "groups and backreferences are unavailable"
        )
    if re.search(r"[+*?][+*?]", query):
        raise ValueError("Repeated regex quantifiers are unavailable")
    try:
        re.compile(query)
    except re.error as exc:
        raise ValueError("Invalid regular expression") from exc
    return query


def search_history(
    sb,
    user_id: str,
    folder_id: str,
    *,
    q="",
    mode="words",
    fields="all",
    date_from=None,
    date_to=None,
    agent=None,
    session_id=None,
    timezone="UTC",
    limit=20,
    offset=0,
):
    pattern = compile_pattern(q, mode)
    if fields not in {"all", "title"}:
        raise ValueError("Invalid search fields")
    if agent not in {None, "codex", "claude_code"}:
        raise ValueError("Invalid agent")
    if session_id is not None:
        if any(ord(char) < 32 or ord(char) == 127 for char in session_id):
            raise ValueError("Session ID cannot contain control characters")
        session_id = session_id.strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,256}", session_id):
            raise ValueError(
                "Session ID allows letters, numbers, dots, underscores, colons and hyphens"
            )
    if not timezone or len(timezone) > 64:
        raise ValueError("Invalid timezone")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Limit must be between 1 and 50")
    if type(offset) is not int or not 0 <= offset <= 10000:
        raise ValueError("Offset must be between 0 and 10000")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Invalid timezone") from exc
    for value in (date_from, date_to):
        if value is not None:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError("Dates must use YYYY-MM-DD")
            date.fromisoformat(value)
    if date_from and date_to and date_from > date_to:
        raise ValueError("Start date must be on or before end date")
    result = (
        sb.rpc(
            "search_agent_history",
            {
                "p_user_id": user_id,
                "p_folder_id": folder_id,
                "p_pattern": pattern,
                "p_fields": fields,
                "p_first": date_from,
                "p_last": date_to,
                "p_agent": agent,
                "p_session": session_id,
                "p_timezone": timezone,
                "p_limit": limit,
                "p_offset": offset,
                "p_snippet": (q.split()[0] if mode == "words" and q.split() else q)
                if mode != "regex"
                else None,
            },
        )
        .execute()
        .data
    )
    return result


def backfill_search(sb, user_id: str, folder_id: str, limit: int = 10) -> dict:
    """Bounded resumable maintenance. The search request never downloads journals."""
    pending_result = (
        sb.rpc(
            "pending_agent_journal_search",
            {
                "p_user_id": user_id,
                "p_folder_id": folder_id,
                "p_limit": limit,
            },
        )
        .execute()
        .data
    )
    pending = pending_result["days"]
    indexed = 0
    for row in pending[:limit]:
        journal = read_journal(sb, user_id, folder_id, row["journal_date"])
        if journal["status"] != "ok":
            continue
        markdown = journal["markdown"]
        sha = hashlib.sha256(markdown.encode()).hexdigest()
        indexed += bool(index_journal(sb, user_id, folder_id, row["journal_date"], sha, markdown))
    return {
        "indexed_days": indexed,
        "remaining_days": max(0, pending_result["remaining_days"] - indexed),
    }
