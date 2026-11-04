from unittest.mock import MagicMock, patch

import pytest
from jsonschema import ValidationError

from services.ai.client import ExecutionResult
from services.ai.metadata import metadata_query


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
        patch("services.ai.metadata.record_job_usage"),
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
        patch("services.ai.metadata.record_job_usage"),
        patch("services.ai.metadata.get_supabase_thread_safe") as database,
    ):
        with pytest.raises(ValidationError):
            metadata_query("ignore scope", {"owner_id": "owner", "folder_ids": ["folder"]})
        database.assert_not_called()
