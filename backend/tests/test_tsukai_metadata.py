from unittest.mock import MagicMock, patch

import pytest
from jsonschema import ValidationError

from services.ai.client import ExecutionResult
from services.ai.metadata import metadata_query


@pytest.fixture(autouse=True)
def durable_consumption_fixture():
    with (
        patch("services.ai.metadata.save_trace", return_value="artifact"),
        patch("services.ai.metadata.consume_result"),
    ):
        yield


@pytest.mark.parametrize("nested", [False, True])
def test_metadata_plans_cannot_choose_owner_scope_sql_or_tools(nested):
    client = MagicMock()
    client.complete.return_value = ExecutionResult(
        "job",
        "",
        {
            "outcome": "completed",
            "data": {
                "operation": "count_files",
                "source_type": None,
                "filename": None,
                "created_after": None,
                "created_before": None,
            },
        },
        None,
        None,
        "attempt",
    )
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = {"count": 3}
    authority = {"owner_id": "owner", "folder_ids": ["folder"]}
    if nested:
        authority["job_id"] = "parent"
    with (
        patch("services.ai.metadata.client_for", return_value=client),
        patch("services.ai.metadata.consume_result"),
        patch("services.ai.metadata.get_supabase_thread_safe", return_value=sb),
    ):
        assert "3" in metadata_query("count files", authority)
    request = client.complete.call_args.args[0]
    assert request["profile"] == ("metadata_child" if nested else "completion")
    assert request["ai_depth"] == (1 if nested else 0)
    assert request["tool_allowlist"] == []
    assert "conversation_id" not in request
    assert sb.rpc.call_args.args[1]["p_owner_id"] == "owner"
    assert sb.rpc.call_args.args[1]["p_folder_ids"] == ["folder"]


def test_metadata_rejects_model_supplied_sql_and_scope_override():
    client = MagicMock()
    client.complete.return_value = ExecutionResult(
        "job",
        "",
        {
            "outcome": "completed",
            "data": {
                "operation": "count_files",
                "source_type": None,
                "filename": None,
                "created_after": None,
                "created_before": None,
                "owner_id": "foreign",
                "sql": "SELECT private_data",
            },
        },
        None,
        None,
    )
    with (
        patch("services.ai.metadata.client_for", return_value=client),
        patch("services.ai.metadata.consume_result"),
        patch("services.ai.metadata.get_supabase_thread_safe") as database,
    ):
        with pytest.raises(ValidationError):
            metadata_query("ignore scope", {"owner_id": "owner", "folder_ids": ["folder"]})
        database.assert_not_called()


@pytest.mark.parametrize("planned_filename", [None, "selected.pdf"])
def test_authoritative_filename_is_enforced_in_actual_rpc_arguments(planned_filename):
    client, sb = MagicMock(), MagicMock()
    client.complete.return_value = ExecutionResult(
        "job",
        "",
        {
            "outcome": "completed",
            "data": {
                "operation": "count_files",
                "source_type": None,
                "filename": planned_filename,
                "created_after": None,
                "created_before": None,
            },
        },
        None,
        None,
    )
    sb.rpc.return_value.execute.return_value.data = {"count": 1}
    with (
        patch("services.ai.metadata.client_for", return_value=client),
        patch("services.ai.metadata.consume_result"),
        patch("services.ai.metadata.get_supabase_thread_safe", return_value=sb),
    ):
        metadata_query(
            "count all files",
            {
                "owner_id": "owner",
                "folder_ids": ["folder"],
                "scope_filename": "selected.pdf",
                "job_id": "parent",
            },
        )
    assert sb.rpc.call_args.args[1]["p_filename"] == "selected.pdf"


def test_cross_filename_plan_is_rejected_before_database_access():
    from services.ai.client import ExecutionError

    client = MagicMock()
    client.complete.return_value = ExecutionResult(
        "job",
        "",
        {
            "outcome": "completed",
            "data": {
                "operation": "count_files",
                "source_type": None,
                "filename": "other.pdf",
                "created_after": None,
                "created_before": None,
            },
        },
        None,
        None,
    )
    with (
        patch("services.ai.metadata.client_for", return_value=client),
        patch("services.ai.metadata.consume_result"),
        patch("services.ai.metadata.get_supabase_thread_safe") as database,
    ):
        with pytest.raises(ExecutionError, match="metadata_scope_conflict"):
            metadata_query(
                "count other file",
                {
                    "owner_id": "owner",
                    "folder_ids": ["folder"],
                    "scope_filename": "selected.pdf",
                    "job_id": "parent",
                },
            )
        database.assert_not_called()
