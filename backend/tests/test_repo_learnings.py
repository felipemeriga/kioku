"""Learning extraction must not turn proposals or agent claims into proven code."""

import json
from unittest.mock import MagicMock, patch

from services.repo_learnings import apply_updates, journal_entries


def entry(entry_id: str, text: str) -> dict:
    return {
        "id": entry_id,
        "date": "2026-10-29",
        "agent": "codex",
        "captured_at": "2026-10-29T10:00:00-03:00",
        "text": text,
    }


def database():
    sb = MagicMock()
    query = sb.table.return_value.select.return_value.eq.return_value.eq.return_value
    query.order.return_value.limit.return_value.execute.return_value.data = []
    return sb


def test_synthetic_journals_are_excluded():
    meta = {"id": "codex:test:1", "agent": "codex", "captured_at": "2026-10-29T10:00:00-03:00"}
    markdown = (
        "# Kioku agent journal — 2026-10-29\n\n"
        f"## 10:00 — Codex\n<!-- kioku-entry: {json.dumps(meta)} -->\n\n"
        "- Simulação E2E: inventamos um deploy.\n"
    )
    assert journal_entries(markdown, "2026-10-29") == []


def test_session_header_is_not_in_learning_evidence():
    meta = {
        "id": "codex:session:1",
        "agent": "codex",
        "session_id": "session",
        "captured_at": 1793278800000,
    }
    markdown = (
        "# Kioku agent journal — 2026-10-29\n\n"
        "## Codex session `session`\n"
        '<!-- kioku-session: {"agent":"codex","session_id":"session"} -->\n\n'
        "**About:** Investigate retry paths\n\n**Done so far:** Checked old attempts.\n\n"
        f"### 1793278800000 — Codex\n<!-- kioku-entry: {json.dumps(meta)} -->\n\n"
        "- Fixed retry handling.\n\n"
    )
    result = journal_entries(markdown, "2026-10-29")
    assert len(result) == 1
    assert result[0]["text"] == "- Fixed retry handling."


def test_agent_implementation_claim_without_main_sha_stays_reported():
    sb = database()
    item = entry("codex:session:turn", "- Implementamos o filtro e validamos a sintaxe.")
    update = {
        "topic_key": "task-filter",
        "statement": "O agente relatou um filtro de tarefas.",
        "source_ids": [item["id"]],
        "evidence_quote": "Implementamos o filtro",
        "git_sha": "a" * 40,
        "retire": False,
    }
    with patch("services.repo_learnings._extract", return_value=[update]):
        assert (
            apply_updates(
                sb,
                user_id="u",
                folder_id="f",
                new_entries=[item],
                main_commits=["a" * 40],
                head_sha="a" * 40,
            )
            == 1
        )
    row = sb.table.return_value.upsert.call_args.args[0]
    assert row["status"] == "reported"
    assert row["git_sha"] is None
    assert row["source_entries"][0]["id"] == item["id"]


def test_commit_status_requires_sha_in_journal_and_main():
    sb = database()
    sha = "b" * 40
    item = entry("codex:session:turn", f"- Commit {sha} added the filter.")
    update = {
        "topic_key": "task-filter",
        "statement": "O filtro entrou no branch principal.",
        "source_ids": [item["id"]],
        "evidence_quote": f"Commit {sha} added the filter.",
        "git_sha": sha,
        "retire": False,
    }
    with patch("services.repo_learnings._extract", return_value=[update]):
        apply_updates(
            sb, user_id="u", folder_id="f", new_entries=[item], main_commits=[sha], head_sha=sha
        )
    row = sb.table.return_value.upsert.call_args.args[0]
    assert row["status"] == "committed"
    assert row["git_sha"] == sha


def test_cited_sha_not_yet_on_main_remains_reported():
    sb = database()
    sha = "c" * 40
    item = entry("codex:session:turn", f"- Commit {sha} added the filter on a branch.")
    update = {
        "topic_key": "task-filter",
        "statement": "O agente relatou um filtro em uma branch.",
        "source_ids": [item["id"]],
        "evidence_quote": f"Commit {sha} added the filter",
        "git_sha": sha,
        "retire": False,
    }
    with patch("services.repo_learnings._extract", return_value=[update]):
        apply_updates(
            sb, user_id="u", folder_id="f", new_entries=[item], main_commits=[], head_sha="a" * 40
        )
    row = sb.table.return_value.upsert.call_args.args[0]
    assert row["status"] == "reported"
    assert row["git_sha"] == sha


def test_unknown_source_id_is_rejected():
    sb = database()
    item = entry("codex:session:turn", "- Investigamos o filtro.")
    update = {
        "topic_key": "task-filter",
        "statement": "Um fato inventado pelo modelo.",
        "source_ids": ["missing"],
        "evidence_quote": "Investigamos o filtro",
        "git_sha": None,
        "retire": False,
    }
    with patch("services.repo_learnings._extract", return_value=[update]):
        assert (
            apply_updates(
                sb,
                user_id="u",
                folder_id="f",
                new_entries=[item],
                main_commits=[],
                head_sha="a" * 40,
            )
            == 0
        )
    sb.table.return_value.upsert.assert_not_called()


def test_claim_without_exact_source_quote_is_rejected():
    sb = database()
    item = entry("codex:session:turn", "- Nós apenas propusemos testar o cache.")
    update = {
        "topic_key": "cache-live",
        "statement": "O cache foi implementado no produto.",
        "source_ids": [item["id"]],
        "evidence_quote": "cache foi implementado",
        "git_sha": None,
        "retire": False,
    }
    with patch("services.repo_learnings._extract", return_value=[update]):
        assert (
            apply_updates(
                sb,
                user_id="u",
                folder_id="f",
                new_entries=[item],
                main_commits=[],
                head_sha="a" * 40,
            )
            == 0
        )
    sb.table.return_value.upsert.assert_not_called()


def test_mcp_learning_reads_reject_out_of_scope_repository():
    import mcp_server

    token = mcp_server._current_user_id.set("u1")
    try:
        with (
            patch("mcp_server.get_supabase", return_value=MagicMock()),
            patch("mcp_server._resolve_repo", return_value=(None, None)),
        ):
            days = json.loads(mcp_server.list_agent_journal_days("another-repo", 2026))
            learnings = json.loads(mcp_server.get_repo_learnings("another-repo"))
        assert days["status"] == learnings["status"] == "error"
        assert "outside this key's scope" in days["error"]
    finally:
        mcp_server._current_user_id.reset(token)
