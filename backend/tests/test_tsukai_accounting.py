from unittest.mock import MagicMock, patch

from services.ai.accounting import record_job_usage, record_native_usage
from services.ai.client import ExecutionResult
from services.ai.scope import ExecutionScope


def test_unknown_counters_remain_null_not_zero():
    sb = MagicMock()
    with patch("services.ai.accounting.get_supabase_thread_safe", return_value=sb):
        record_native_usage(
            ExecutionScope("owner"),
            "query_rewrite",
            "haiku",
            ExecutionResult("job", "text", None, None, None, "attempt"),
        )
    row = sb.table.return_value.upsert.call_args.args[0]
    assert row["list_equivalent_usd"] is None
    assert row["usage"] is None
    assert row["complete"] is False
    assert row["billing_mode"] == "subscription"


def test_failed_and_repair_attempts_are_recorded_separately_without_summing_cumulative_counters():
    client = MagicMock()
    client.usage.return_value = {
        "attempts": [
            {
                "attempt_id": "bad",
                "status": "failed",
                "model": "haiku",
                "usage": {"complete": True, "list_equivalent_usd": 0.01, "counter_reset": False},
            },
            {
                "attempt_id": "repair",
                "status": "completed",
                "model": "haiku",
                "usage": {"complete": False, "list_equivalent_usd": None, "counter_reset": True},
            },
        ]
    }
    sb = MagicMock()
    with patch("services.ai.accounting.get_supabase_thread_safe", return_value=sb):
        record_job_usage(client, ExecutionScope("owner"), "text_to_sql", "haiku", "job")
    rows = [call.args[0] for call in sb.table.return_value.upsert.call_args_list]
    assert [row["attempt_id"] for row in rows] == ["bad", "repair"]
    assert rows[0]["outcome"] == "failed"
    assert rows[1]["usage"]["counter_reset"] is True
    assert rows[1]["list_equivalent_usd"] is None
