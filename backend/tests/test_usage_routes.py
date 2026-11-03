import asyncio
import inspect
import unittest
from unittest.mock import MagicMock, patch


def _run(coro):
    if not inspect.isawaitable(coro):
        return coro
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _sb(usage_rows, conv_rows):
    sb = MagicMock()
    sb.auth.admin.get_user_by_id.return_value.user.email = "felipe.meriga@gmail.com"
    usage_tbl = MagicMock()
    usage_tbl.select.return_value.eq.return_value.execute.return_value.data = usage_rows
    conv_tbl = MagicMock()
    conv_tbl.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = (
        conv_rows
    )
    sb.table.side_effect = lambda name: usage_tbl if name == "chat_usage" else conv_tbl
    return sb, usage_tbl


USAGE_ROWS = [
    {
        "conversation_id": "c1",
        "model": "sonnet",
        "input_tokens": 1000,
        "output_tokens": 500,
        "created_at": "2026-10-05T10:00:00+00:00",
    },
    {
        "conversation_id": "c1",
        "model": "haiku",
        "input_tokens": 2000,
        "output_tokens": 100,
        "created_at": "2026-10-06T10:00:00+00:00",
    },
    {
        "conversation_id": "c2",
        "model": "sonnet",
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "created_at": "2026-09-01T10:00:00+00:00",
    },
]
CONV_ROWS = [{"id": "c1", "title": "First"}, {"id": "c2", "title": "Second"}]


class TestUsageByConversation(unittest.TestCase):
    def test_aggregates_and_sorts_by_cost(self):
        from routes.usage import usage_by_conversation

        sb, usage_tbl = _sb(USAGE_ROWS, CONV_ROWS)
        with patch("routes.usage.get_supabase", return_value=sb):
            out = _run(usage_by_conversation(user_id="u1"))

        # scoped to caller
        self.assertEqual(usage_tbl.select.return_value.eq.call_args.args, ("user_id", "u1"))
        # c2 ($3.0) outranks c1 ($0.013)
        self.assertEqual(out[0]["conversation_id"], "c2")
        self.assertEqual(out[0]["title"], "Second")
        self.assertEqual(out[0]["cost_usd"], 3.0)
        c1 = next(r for r in out if r["conversation_id"] == "c1")
        self.assertEqual(c1["input_tokens"], 3000)
        self.assertEqual(c1["output_tokens"], 600)
        # sonnet(1000,500)=0.0105 + haiku(2000,100)=0.0025 = 0.013
        self.assertAlmostEqual(c1["cost_usd"], 0.013, places=6)

    def test_empty(self):
        from routes.usage import usage_by_conversation

        sb, _ = _sb([], [])
        with patch("routes.usage.get_supabase", return_value=sb):
            out = _run(usage_by_conversation(user_id="u1"))
        self.assertEqual(out, [])


class TestUsageByMonth(unittest.TestCase):
    def test_groups_by_month_newest_first(self):
        from routes.usage import usage_by_month

        sb, usage_tbl = _sb(USAGE_ROWS, CONV_ROWS)
        with patch("routes.usage.get_supabase", return_value=sb):
            out = _run(usage_by_month(user_id="u1"))

        self.assertEqual(usage_tbl.select.return_value.eq.call_args.args, ("user_id", "u1"))
        self.assertEqual([r["month"] for r in out], ["2026-10", "2026-09"])
        oct_row = out[0]
        self.assertEqual(oct_row["input_tokens"], 3000)
        self.assertEqual(oct_row["output_tokens"], 600)
        self.assertAlmostEqual(oct_row["cost_usd"], 0.013, places=6)
        self.assertEqual(out[1]["cost_usd"], 3.0)


class TestAttributedUsage(unittest.TestCase):
    def test_sums_rounds_into_one_response_and_attributes_mihari(self):
        from routes.usage import usage_attribution

        rows = [
            {
                "source": "chat",
                "operation": "answer",
                "folder_id": None,
                "conversation_id": "c1",
                "response_id": "r1",
                "round_number": 1,
                "model": "claude-haiku-4-5-20251001",
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_write_5m_tokens": 0,
                "cache_write_1h_tokens": 0,
                "cache_read_tokens": 20,
                "list_cost_usd": "0.000037",
                "created_at": "2026-11-03T12:00:00Z",
            },
            {
                "source": "chat",
                "operation": "answer",
                "folder_id": None,
                "conversation_id": "c1",
                "response_id": "r1",
                "round_number": 2,
                "model": "claude-haiku-4-5-20251001",
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_write_5m_tokens": 0,
                "cache_write_1h_tokens": 0,
                "cache_read_tokens": 0,
                "list_cost_usd": "0.000035",
                "created_at": "2026-11-03T12:00:01Z",
            },
            {
                "source": "mihari",
                "operation": "documentation",
                "folder_id": "f1",
                "conversation_id": None,
                "response_id": None,
                "round_number": None,
                "model": "claude-haiku-4-5-20251001",
                "input_tokens": 100,
                "output_tokens": 10,
                "cache_write_5m_tokens": 0,
                "cache_write_1h_tokens": 0,
                "cache_read_tokens": 0,
                "list_cost_usd": "0.00015",
                "created_at": "2026-11-03T12:00:02Z",
            },
        ]
        sb = MagicMock()
        sb.auth.admin.get_user_by_id.return_value.user.email = "felipe.meriga@gmail.com"
        tables = {
            name: MagicMock()
            for name in ("llm_usage_events", "folders", "conversations", "watched_repos")
        }
        sb.table.side_effect = tables.__getitem__
        tables["watched_repos"].select().execute.return_value.data = [
            {
                "user_id": "other-user",
                "folder_id": "f1",
                "remote_url": "git@example/repo",
                "branch": "main",
                "last_run_at": None,
                "last_error": None,
            }
        ]
        ledger_query = tables["llm_usage_events"].select().gte().lt().order().range()
        ledger_query.execute.return_value.data = rows
        folder_query = tables["folders"].select().in_()
        folder_query.execute.return_value.data = [{"id": "f1", "name": "Kioku"}]
        conversation_query = tables["conversations"].select().in_()
        conversation_query.execute.return_value.data = [{"id": "c1", "title": "Question"}]
        with patch("routes.usage.get_supabase", return_value=sb):
            result = usage_attribution(month="2026-11", user_id="u1")
        assert result["total_cost_usd"] == "0.000222"
        assert result["by_source"] == {"chat": "0.000072", "mihari": "0.00015"}
        assert result["responses"][0]["title"] == "Question"
        assert [item["round"] for item in result["responses"][0]["rounds"]] == [1, 2]
        assert result["by_repository"][0]["name"] == "Kioku"
        assert result["mihari_calls"][0]["operation"] == "documentation"


def test_usage_admin_rejects_other_users_before_reading_usage():
    from fastapi import HTTPException

    from routes.usage import usage_attribution

    sb = MagicMock()
    sb.auth.admin.get_user_by_id.return_value.user.email = "other@example.com"
    with patch("routes.usage.get_supabase", return_value=sb):
        try:
            usage_attribution(month="2026-11", user_id="other")
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("admin access must be enforced")
    sb.table.assert_not_called()
