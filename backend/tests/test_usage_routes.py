import asyncio
import unittest
from unittest.mock import MagicMock, patch


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _sb(usage_rows, conv_rows):
    sb = MagicMock()
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
