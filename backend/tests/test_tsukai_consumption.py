from unittest.mock import MagicMock, patch

import httpx

from services.ai.consumption import consume_result, finish_receipt
from services.ai.scope import ExecutionScope


def test_consumed_output_is_durable_and_successful_when_ack_transport_fails():
    sb = MagicMock()
    with (
        patch("services.ai.consumption.get_supabase_thread_safe", return_value=sb),
        patch("services.ai.consumption.finish_receipt", side_effect=httpx.ConnectError("offline")),
    ):
        consume_result(
            ExecutionScope("owner"),
            "query_rewrite",
            "completion",
            "job",
            "completion.query_rewrite",
            "job",
            {"text": "resolved", "model": "haiku"},
        )
    row = sb.table.return_value.upsert.call_args.args[0]
    assert row["job_id"] == "job" and row["payload"]["text"] == "resolved"
    assert row["scope"]["expires_at"] is None


def test_receipt_copies_usage_before_ack_and_records_completion():
    sb, client = MagicMock(), MagicMock()
    client.status.return_value = {"status": "completed"}
    calls = []
    client.acknowledge.side_effect = lambda *args: calls.append("ack")
    receipt = {
        "job_id": "job",
        "scope": {"owner_id": "owner", "folder_ids": []},
        "operation": "query_rewrite",
        "profile": "completion",
        "consumer": "completion.query_rewrite",
        "reference": "job",
        "payload": {"model": "haiku"},
    }
    with (
        patch("services.ai.consumption.get_supabase_thread_safe", return_value=sb),
        patch("services.ai.facade.client_for", return_value=client),
        patch(
            "services.ai.consumption.record_job_usage",
            side_effect=lambda *args, **kwargs: calls.append("usage"),
        ),
    ):
        finish_receipt(receipt)
    assert calls == ["usage", "ack"]
    assert sb.table.return_value.update.call_args.args[0] == {
        "processed": True,
        "acknowledged": True,
    }


def test_failed_terminal_receipt_copies_usage_without_claiming_remote_success_ack():
    sb, client = MagicMock(), MagicMock()
    client.status.return_value = {"status": "failed"}
    receipt = {
        "job_id": "job",
        "scope": {"owner_id": "owner", "folder_ids": []},
        "operation": "text_to_sql",
        "profile": "completion",
        "consumer": "metadata",
        "reference": "artifact",
        "payload": {"model": "haiku"},
    }
    with (
        patch("services.ai.consumption.get_supabase_thread_safe", return_value=sb),
        patch("services.ai.facade.client_for", return_value=client),
        patch("services.ai.consumption.record_job_usage"),
    ):
        finish_receipt(receipt)
    client.acknowledge.assert_not_called()
    assert sb.table.return_value.update.call_args.args[0] == {
        "processed": True,
        "acknowledged": False,
    }
