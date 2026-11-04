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
            "schema_version": 1,
            "outcome": "completed",
            "missing_inputs": [],
            "failure": None,
            "warnings": [],
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
            "schema_version": 1,
            "outcome": "completed",
            "missing_inputs": [],
            "failure": None,
            "warnings": [],
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
            "schema_version": 1,
            "outcome": "completed",
            "missing_inputs": [],
            "failure": None,
            "warnings": [],
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
            "schema_version": 1,
            "outcome": "completed",
            "missing_inputs": [],
            "failure": None,
            "warnings": [],
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


@pytest.mark.parametrize(
    "outcome,missing,failure",
    [
        ("needs_input", [{"field": "source", "reason": "missing"}], None),
        ("completed", [{"field": "source", "reason": "missing"}], None),
        ("completed", [], {"code": "unsupported", "message": "Unsupported"}),
    ],
)
def test_metadata_rejects_cross_outcome_data_before_scoped_rpc(outcome, missing, failure):
    client = MagicMock()
    client.complete.return_value = ExecutionResult(
        "job",
        "",
        {
            "schema_version": 1,
            "outcome": outcome,
            "data": {
                "operation": "count_files",
                "source_type": None,
                "filename": None,
                "created_after": None,
                "created_before": None,
            },
            "missing_inputs": missing,
            "failure": failure,
            "warnings": [],
        },
        None,
        None,
    )
    with (
        patch("services.ai.metadata.client_for", return_value=client),
        patch("services.ai.metadata.get_supabase_thread_safe") as database,
    ):
        with pytest.raises(ValidationError):
            metadata_query("count files", {"owner_id": "owner", "folder_ids": ["folder"]})
        database.assert_not_called()


@pytest.mark.parametrize("accounting_fails", [False, True])
def test_accepted_metadata_provider_failure_keeps_original_error_and_tracks_usage(accounting_fails):
    from services.ai.client import ExecutionError

    client = MagicMock()
    client.last_job_id = "accepted-metadata"
    failure = ExecutionError("quota_limited")
    client.complete.side_effect = failure
    with (
        patch("services.ai.metadata.client_for", return_value=client),
        patch(
            "services.ai.metadata.consume_result",
            side_effect=RuntimeError("receipt offline") if accounting_fails else None,
        ) as receipt,
        patch("services.ai.metadata.get_supabase_thread_safe") as database,
    ):
        with pytest.raises(ExecutionError) as raised:
            metadata_query("count files", {"owner_id": "owner", "folder_ids": ["folder"]})
    assert raised.value is failure
    database.assert_not_called()
    assert receipt.call_args.args[3] == "accepted-metadata"
    assert receipt.call_args.args[-1]["acknowledge_completed"] is False
    assert receipt.call_args.args[-1]["outcome"] == "quota_limited"


def test_nested_metadata_transport_failure_defers_receipt_until_root_artifact():
    from services.ai.client import ExecutionError
    from services.ai.metadata import consume_metadata

    client, consumed = MagicMock(), []
    client.last_job_id = "accepted-child"
    client.complete.side_effect = ExecutionError("missing_terminal")
    with (
        patch("services.ai.metadata.client_for", return_value=client),
        patch("services.ai.metadata.consume_result") as receipt,
    ):
        with pytest.raises(ExecutionError, match="missing_terminal"):
            metadata_query(
                "count files",
                {"owner_id": "owner", "folder_ids": ["folder"], "job_id": "root"},
                on_consumption=consumed.append,
            )
        receipt.assert_not_called()
        consume_metadata(consumed[0], "persisted-root-artifact")
    assert receipt.call_args.args[5] == "persisted-root-artifact"
    assert receipt.call_args.args[-1]["acknowledge_completed"] is False


@pytest.mark.parametrize("nested", [False, True])
def test_multipart_metadata_plans_from_supplied_authorized_scope_without_database_access(nested):
    import json

    from services.ai.metadata import ENVELOPE_SCHEMA, PLAN_PROMPT

    question = (
        "How many documents are in the knowledge base, and what are the main "
        "document types and topics?"
    )
    client, sb = MagicMock(), MagicMock()
    plan = {
        "operation": "count_files",
        "source_type": None,
        "filename": None,
        "created_after": None,
        "created_before": None,
    }
    client.complete.return_value = ExecutionResult(
        "job",
        "",
        {
            "schema_version": 1,
            "outcome": "completed",
            "data": plan,
            "missing_inputs": [],
            "failure": None,
            "warnings": [],
        },
        None,
        None,
        "attempt",
    )
    authority = {"owner_id": "owner", "folder_ids": ["owned-a", "owned-b"], "scope_filename": None}
    if nested:
        authority["job_id"] = "parent"
    sb.rpc.return_value.execute.return_value.data = {"count": 7}
    with (
        patch("services.ai.metadata.client_for", return_value=client),
        patch("services.ai.metadata.get_supabase_thread_safe", return_value=sb),
    ):
        assert json.loads(metadata_query(question, authority)) == {"count": 7}
    request = client.complete.call_args.args[0]
    assert request["system_prompt"] == PLAN_PROMPT
    assert "plan-only translator, not a database operator" in PLAN_PROMPT
    assert "already owns the database connection, authorization" in PLAN_PROMPT
    assert "Unsupported parts do not prevent planning a supported part" in PLAN_PROMPT
    assert "never knowledge_base_access or infrastructure" in PLAN_PROMPT
    assert request["tool_allowlist"] == [] and request["response_schema"] == ENVELOPE_SCHEMA
    assert json.loads(request["prompt"]) == {
        "question": question,
        "authorized_scope": {"folder_ids": ["owned-a", "owned-b"], "filename": None},
    }
    assert sb.rpc.call_args.args == (
        "tsukai_scoped_metadata",
        {
            "p_owner_id": "owner",
            "p_folder_ids": ["owned-a", "owned-b"],
            "p_operation": "count_files",
            "p_source_type": None,
            "p_filename": None,
            "p_created_after": None,
            "p_created_before": None,
        },
    )


def test_genuine_missing_intent_still_cannot_reach_database_execution():
    from services.ai.client import ExecutionError

    client = MagicMock()
    client.complete.return_value = ExecutionResult(
        "job",
        "",
        {
            "schema_version": 1,
            "outcome": "needs_input",
            "data": None,
            "missing_inputs": [
                {"field": "question", "reason": "Specify which metadata to inspect"}
            ],
            "failure": None,
            "warnings": [],
        },
        None,
        None,
        "attempt",
    )
    with (
        patch("services.ai.metadata.client_for", return_value=client),
        patch("services.ai.metadata.get_supabase_thread_safe") as database,
    ):
        with pytest.raises(ExecutionError, match="metadata_invalid_outcome"):
            metadata_query("", {"owner_id": "owner", "folder_ids": ["owned"]})
    database.assert_not_called()
