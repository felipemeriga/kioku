"""Journal validation and scoped MCP access."""

import hashlib
import json
from datetime import date
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from services.agent_journal import (
    inspect_journal,
    journal_entries,
    journal_sessions,
    local_journal_day,
    local_journal_days,
    read_journals_in_range,
)

DAY = "2026-10-29"
META = {
    "id": "codex:session:turn",
    "agent": "codex",
    "session_id": "session",
    "turn_id": "turn",
    "captured_at": "2026-10-29T10:00:00-03:00",
    "source_ref": "codex://session/turn",
    "schema": 1,
}


def journal(meta=META):
    return (
        f"# Kioku agent journal — {DAY}\n\n"
        f"## 10:00 — Codex\n<!-- kioku-entry: {json.dumps(meta)} -->\n\n"
        "- Fixed query\n\n"
    )


def test_inspect_records_hash_and_provenance():
    text = journal()
    got = inspect_journal(text, DAY)
    assert got["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert got["entry_count"] == 1
    assert got["agents"] == ["codex"]


def test_journal_sessions_groups_turns_and_uses_latest_summary():
    first = journal(
        {**META, "session_title": "Investigate retries", "session_summary": "Checked retry paths."}
    )
    second_meta = {
        **META,
        "id": "codex:session:turn2",
        "turn_id": "turn2",
        "captured_at": "2026-10-29T10:30:00-03:00",
        "session_title": "Fix retry handling",
        "session_summary": "Checked retry paths and fixed NotFound recovery.",
    }
    text = (
        first
        + f"## 10:30 — Codex\n<!-- kioku-entry: {json.dumps(second_meta)} -->\n\n- Fixed retry\n\n"
    )
    sessions = journal_sessions(text)
    assert len(sessions) == 1
    assert sessions[0]["entry_count"] == 2
    assert sessions[0]["title"] == "Fix retry handling"
    assert sessions[0]["summary"] == "Checked retry paths and fixed NotFound recovery."


def test_journal_accepts_detailed_session_overview():
    detailed = "The user wants to understand and improve the repository. " * 22
    assert len(detailed) > 800
    assert inspect_journal(journal({**META, "session_summary": detailed}), DAY)["entry_count"] == 1


def test_grouped_session_header_is_not_part_of_turn_entries():
    first_ms = 1793278800000
    meta = {
        **META,
        "captured_at": first_ms,
        "session_title": "Fix retry handling",
        "session_summary": "Investigated and fixed retry handling.",
    }
    text = (
        f"# Kioku agent journal — {DAY}\n\n"
        "## Codex session `session`\n"
        '<!-- kioku-session: {"agent":"codex","session_id":"session"} -->\n\n'
        "**About:** Fix retry handling\n\n"
        "**Done so far:** Investigated and fixed retry handling.\n\n"
        f"### {first_ms} — Codex\n<!-- kioku-entry: {json.dumps(meta)} -->\n\n"
        "- Fixed the retry\n\n"
    )
    parsed = journal_entries(text)
    assert len(parsed) == 1
    assert "**About:**" not in parsed[0]["block"]
    assert inspect_journal(text, DAY)["entry_count"] == 1
    assert journal_sessions(text)[0]["title"] == "Fix retry handling"


def test_epoch_journals_project_adjacent_utc_days_into_viewer_day():
    first_ms = 1793316600000  # 2026-10-29 23:30 UTC
    second_ms = 1793320200000  # 2026-10-30 00:30 UTC
    first = {**META, "captured_at": first_ms}
    second = {**META, "id": "codex:session:turn2", "turn_id": "turn2", "captured_at": second_ms}
    journals = [
        {
            "journal_date": "2026-10-29",
            "revision": 1,
            "markdown": (
                f"# Kioku agent journal — 2026-10-29\n\n## {first_ms} — Codex\n"
                f"<!-- kioku-entry: {json.dumps(first)} -->\n\n- First\n\n"
            ),
        },
        {
            "journal_date": "2026-10-30",
            "revision": 2,
            "markdown": (
                f"# Kioku agent journal — 2026-10-30\n\n## {second_ms} — Codex\n"
                f"<!-- kioku-entry: {json.dumps(second)} -->\n\n- Second\n\n"
            ),
        },
    ]
    assert inspect_journal(journals[0]["markdown"], "2026-10-29")["entry_count"] == 1
    assert inspect_journal(journals[1]["markdown"], "2026-10-30")["entry_count"] == 1
    tz = ZoneInfo("America/Sao_Paulo")
    days = local_journal_days(journals, tz, 2026, 10)
    assert days == [
        {"journal_date": "2026-10-29", "revision": 2, "entry_count": 2, "agents": ["codex"]}
    ]
    result = local_journal_day(journals, tz, date(2026, 10, 29))
    assert result["status"] == "ok"
    assert result["sessions"][0]["entry_count"] == 2
    assert result["markdown"].count("## Codex session") == 1
    assert result["markdown"].index("## Codex session") < result["markdown"].index("- First")
    assert result["markdown"].index("- First") < result["markdown"].index("- Second")


def test_legacy_writer_day_can_be_two_days_from_viewer_day():
    old = {**META, "captured_at": "2026-10-29T23:30:00-12:00"}
    source = journal(old)
    journals = [{"journal_date": "2026-10-29", "revision": 1, "markdown": source}]
    days = local_journal_days(journals, ZoneInfo("Pacific/Kiritimati"), 2026, 10)
    assert [day["journal_date"] for day in days] == ["2026-10-31"]


def test_local_day_lookup_includes_two_adjacent_source_dates():
    sb = MagicMock()
    chain = sb.table.return_value
    for method in ("select", "eq", "eq"):
        chain = getattr(chain, method).return_value
    after_range = chain.gte.return_value.lte.return_value
    after_range.order.return_value.limit.return_value.execute.return_value.data = []
    read_journals_in_range(sb, "u", "repo", date(2026, 10, 31), date(2026, 10, 31))
    chain.gte.assert_called_once_with("journal_date", "2026-10-29")
    chain.gte.return_value.lte.assert_called_once_with("journal_date", "2026-11-02")


@pytest.mark.parametrize(
    "text,date",
    [
        (journal(), "2026-10-28"),
        (journal() + journal().split("## 10:00", 1)[1], DAY),
        (journal({**META, "agent": "unknown"}), DAY),
        (journal({**META, "captured_at": "2026-10-28T10:00:00-03:00"}), DAY),
    ],
)
def test_rejects_mismatched_or_invalid_entries(text, date):
    with pytest.raises(ValueError):
        inspect_journal(text, date)


def test_mcp_rejects_unscoped_journal_access():
    import mcp_server

    token = mcp_server._current_user_id.set("u1")
    try:
        with patch("mcp_server.get_supabase", return_value=MagicMock()):
            result = json.loads(mcp_server.get_agent_journal(folder="", date=DAY))
        assert result["status"] == "error"
        assert "explicit folder" in result["error"]
    finally:
        mcp_server._current_user_id.reset(token)


def test_mcp_rejects_repository_outside_key_scope():
    import mcp_server

    token = mcp_server._current_user_id.set("u1")
    try:
        with (
            patch("mcp_server.get_supabase", return_value=MagicMock()),
            patch("mcp_server._resolve_repo", return_value=(None, None)),
        ):
            result = json.loads(mcp_server.get_agent_journal(folder="other-repo", date=DAY))
        assert result["status"] == "error"
        assert "outside this key's scope" in result["error"]
    finally:
        mcp_server._current_user_id.reset(token)
