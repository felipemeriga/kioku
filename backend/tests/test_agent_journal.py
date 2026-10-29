"""Journal validation and scoped MCP access."""

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest

from services.agent_journal import inspect_journal

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
