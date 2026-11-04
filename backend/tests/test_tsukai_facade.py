from unittest.mock import MagicMock, patch

import jwt
import pytest

from services.ai.client import ExecutionError, ExecutionResult
from services.ai.facade import native_completion
from services.ai.scope import ExecutionScope, execution_scope, operation_scope, sign_capability


def test_operation_scope_blocks_nested_generation_and_limits_metadata_child():
    with execution_scope(ExecutionScope("owner", harness_tool=True, parent_job_id="parent")):
        with pytest.raises(PermissionError):
            operation_scope("query_rewrite")
        assert operation_scope("text_to_sql").ai_depth == 1
    with execution_scope(ExecutionScope("owner", ai_depth=1)):
        with pytest.raises(PermissionError):
            operation_scope("text_to_sql")


def test_grant_contains_exact_owner_scope_and_operation(monkeypatch):
    monkeypatch.setenv("TSUKAI_CAPABILITY_KEY", "x" * 32)
    scope = ExecutionScope("owner", ("folder",), caller="mcp")
    grant = sign_capability(scope, "text_to_sql", "completion")
    claims = jwt.decode(grant, "x" * 32, algorithms=["HS256"], audience="tsukai")
    assert claims["owner_id"] == "owner"
    assert claims["folder_ids"] == ["folder"]
    assert claims["operations"] == ["text_to_sql"]
    assert claims["profiles"] == ["completion"]
    assert claims["sub"] == "mcp"


def test_fresh_completion_never_uses_resume_and_preserves_unknown_usage(monkeypatch):
    monkeypatch.setenv("TSUKAI_NATIVE_TASKS", "text_to_sql")
    monkeypatch.setenv("TSUKAI_CREDENTIAL_OWNER_ID", "owner")
    client = MagicMock()
    client.complete.return_value = ExecutionResult(
        "job",
        "SELECT 1",
        {
            "schema_version": 1,
            "outcome": "completed",
            "data": {"text": "SELECT 1"},
            "missing_inputs": [],
            "failure": None,
            "warnings": [],
        },
        None,
        "native",
    )
    with execution_scope(ExecutionScope("owner", ("folder",), caller="mcp")):
        with (
            patch("services.ai.facade.client_for", return_value=client),
            patch("services.ai.facade.consume_result"),
        ):
            result = native_completion(
                operation="text_to_sql",
                model="haiku",
                messages=[{"role": "user", "content": "count documents"}],
                system=None,
                max_tokens=256,
                tools=None,
            )
    request = client.complete.call_args.args[0]
    assert request["profile"] == "completion"
    assert request["tool_allowlist"] == []
    assert "conversation_id" not in request
    assert "native_session_id" not in request
    assert result.content[0].text == "SELECT 1"
    assert result.execution.usage is None
    client.close.assert_called_once()


def test_mihari_cannot_accidentally_relay_generation_through_backend(monkeypatch):
    monkeypatch.setenv("TSUKAI_NATIVE_TASKS", "text_to_sql")
    monkeypatch.setenv("TSUKAI_CREDENTIAL_OWNER_ID", "owner")
    with execution_scope(ExecutionScope("owner", caller="mihari")):
        with pytest.raises(ExecutionError, match="direct_route_required"):
            native_completion(
                operation="text_to_sql",
                model="haiku",
                messages=[],
                system=None,
                max_tokens=1,
                tools=None,
            )


@pytest.mark.parametrize("accounting_fails", [False, True])
def test_accepted_native_failure_is_tracked_without_masking_failure(monkeypatch, accounting_fails):
    monkeypatch.setenv("TSUKAI_NATIVE_TASKS", "contextual")
    monkeypatch.setenv("TSUKAI_CREDENTIAL_OWNER_ID", "owner")
    client = MagicMock()
    client.last_job_id = "accepted-job"
    failure = ExecutionError("native_process_failed")
    client.complete.side_effect = failure
    with (
        execution_scope(ExecutionScope("owner", ("folder",))),
        patch("services.ai.facade.client_for", return_value=client),
        patch(
            "services.ai.facade.consume_result",
            side_effect=RuntimeError("database unavailable") if accounting_fails else None,
        ) as receipt,
    ):
        with pytest.raises(ExecutionError) as raised:
            native_completion(
                operation="contextual",
                model="haiku",
                messages=[{"role": "user", "content": "source"}],
                system=None,
                max_tokens=120,
                tools=None,
            )
    assert raised.value is failure
    assert receipt.call_args.args[3] == "accepted-job"
    assert receipt.call_args.args[-1]["acknowledge_completed"] is False
    assert receipt.call_args.args[-1]["outcome"] == "native_process_failed"
