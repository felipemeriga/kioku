from unittest.mock import MagicMock, patch

import pytest
from jsonschema import validate

from services.ai.client import ExecutionError, ExecutionResult
from services.ai.contracts import completion_schema, completion_text
from services.ai.facade import native_completion
from services.ai.registry import TASK_POLICIES
from services.ai.scope import ExecutionScope, execution_scope


def envelope(data, outcome="completed"):
    return {
        "schema_version": 1,
        "outcome": outcome,
        "data": data,
        "missing_inputs": [],
        "failure": None,
        "warnings": [],
    }


OPERATIONS = [
    name
    for name, policy in TASK_POLICIES.items()
    if policy.native_verified and policy.profile == "completion"
]


@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_native_completion_emits_registered_schema_and_unwraps_task_data(
    operation, monkeypatch
):
    monkeypatch.setenv("TSUKAI_NATIVE_TASKS", operation)
    monkeypatch.setenv("TSUKAI_CREDENTIAL_OWNER_ID", "owner")
    kind = TASK_POLICIES[operation].output
    data = (
        {"queries": ["first search", "second search", "third search"]}
        if kind == "queries"
        else (
            {
                "value": (
                    {"updates": []}
                    if operation == "folder_summary_rollup"
                    else {"overview": {"purpose": "Purpose", "description": "Grounded description"}}
                )
            }
            if kind == "json"
            else {"text": "resolved task"}
        )
    )
    client = MagicMock()
    client.complete.return_value = ExecutionResult(
        "job", "raw native envelope", envelope(data), None, None
    )
    with (
        execution_scope(ExecutionScope("owner")),
        patch("services.ai.facade.client_for", return_value=client),
        patch("services.ai.facade.consume_result"),
    ):
        result = native_completion(
            operation=operation,
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": "task"}],
            system=None,
            max_tokens=1024,
            tools=None,
        )
    request = client.complete.call_args.args[0]
    assert request["response_schema"] == completion_schema(operation)
    validate(envelope(data), request["response_schema"])
    assert result.content[0].text != "raw native envelope"


@pytest.mark.parametrize(
    "structured,code",
    [
        (None, "invalid_completion_envelope"),
        (envelope({"text": ""}), "invalid_completion_envelope"),
        (envelope({"text": "   "}), "invalid_completion_envelope"),
        (envelope({"text": "Could you clarify which repository?"}), "interaction_required"),
        (envelope({"unexpected": "question"}), "invalid_completion_envelope"),
        (
            {
                **envelope(None, "needs_input"),
                "missing_inputs": [{"field": "repo", "reason": "missing"}],
            },
            "needs_input",
        ),
        ({**envelope(None, "failed"), "failure": {"code": "unsupported"}}, "failed"),
    ],
)
def test_free_prose_questions_missing_inputs_and_invalid_data_never_become_success(
    structured, code
):
    with pytest.raises(ExecutionError, match=code):
        completion_text("query_rewrite", structured)


@pytest.mark.parametrize("operation", ["folder_summary_rollup", "folder_summary_reground"])
def test_json_task_rejects_a_question_instead_of_its_known_shape(operation):
    with pytest.raises(ExecutionError, match="invalid_completion_envelope"):
        completion_text(
            operation, envelope({"value": {"question": "Which repo should I inspect?"}})
        )
