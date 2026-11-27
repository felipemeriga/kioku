import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.prompt_values import StringPromptValue

from services.ai.client import ExecutionError, ExecutionResult
from services.ai.evaluation import SubscriptionJudge
from services.ai.facade import native_completion
from services.ai.scope import ExecutionScope, current_scope, execution_scope


def test_vision_completion_is_scoped_and_never_embeds_image_bytes_in_text_prompt():
    data = base64.b64encode(b"\x89PNG\r\n\x1a\nfixture").decode()
    client = MagicMock()
    client.complete.return_value = ExecutionResult(
        "job",
        "",
        {
            "schema_version": 1,
            "outcome": "completed",
            "data": {"text": "words"},
            "missing_inputs": [],
            "failure": None,
            "warnings": [],
        },
        None,
        "session",
    )
    with (
        execution_scope(ExecutionScope("another-user", ("folder",))),
        patch("services.ai.facade.client_for", return_value=client),
        patch("services.ai.facade.consume_result"),
    ):
        response = native_completion(
            operation="image_ocr",
            model="haiku",
            system=None,
            max_tokens=4096,
            tools=None,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": data},
                        },
                        {"type": "text", "text": "read image"},
                    ],
                }
            ],
        )
    assert response.content[0].text == "words"
    request = client.complete.call_args.args[0]
    assert request["owner_id"] == "another-user" and request["folder_ids"] == ["folder"]
    assert request["input_images"] == [{"media_type": "image/png", "data": data}]
    assert data not in request["prompt"]
    with (
        execution_scope(ExecutionScope("another-user")),
        pytest.raises(ExecutionError, match="unsupported_content"),
    ):
        native_completion(
            operation="image_ocr",
            model="haiku",
            system=None,
            max_tokens=1024,
            tools=None,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "url", "url": "https://forbidden.invalid"},
                        }
                    ],
                }
            ],
        )


def test_ragas_judge_preserves_scope_across_async_threads():
    seen = []

    def answer(**kwargs):
        seen.append(current_scope())
        return SimpleNamespace(content=[SimpleNamespace(text='{"score": 1}')])

    judge = SubscriptionJudge(ExecutionScope("another-user", ("folder",)))
    with patch("services.ai.evaluation.complete", side_effect=answer):
        result = asyncio.run(judge.agenerate_text(StringPromptValue(text="score"), n=2))
    assert len(result.generations[0]) == 2
    assert all(
        scope.owner_id == "another-user" and scope.folder_ids == ("folder",) for scope in seen
    )
    assert current_scope() is None
    assert judge.is_finished(result)


@pytest.mark.parametrize("profile", ["chat", "completion"])
def test_evaluation_answer_uses_production_native_bridge_and_cleans_up(profile):
    import json

    from services.rag import answer_question

    sb = MagicMock()
    traces = sb.table.return_value.select.return_value
    traces.eq.return_value = traces
    traces.execute.return_value.data = [{"trace": {"sources": [{"content": "retrieved original"}]}}]
    frame = {
        "done": True,
        "replace": "grounded answer",
        "job_id": "accepted-job",
        "debug": {"tool_calls": [{}], "execution": {"attempt_id": "accepted-attempt"}},
    }
    prepared = {"id": "turn-id", "job_id": None, "request": {"profile": profile}}
    mode = "plain" if profile == "completion" else "deep"
    with (
        patch("services.rag.get_supabase_thread_safe", return_value=sb),
        patch("services.scope.validate_scope_folder") as validate,
        patch("services.scope.descendant_folder_ids", return_value=["folder", "child"]),
        patch("services.ai.chat.prepare_turn", return_value=prepared) as prepare,
        patch("services.ai.chat.stream_turn", return_value=["data: " + json.dumps(frame)]),
    ):
        result = answer_question(
            "question", "tenant", mode=mode, scope_folder_ids=["folder", "child"]
        )
    validate.assert_called_once_with("folder", "tenant")
    assert prepare.call_args.kwargs["owner_id"] == "tenant"
    assert prepare.call_args.kwargs["folder_id"] == "folder"
    assert prepared["job_id"] is None
    assert [call.args for call in traces.eq.call_args_list] == [
        ("owner_id", "tenant"),
        ("job_id", "turn-id" if profile == "completion" else "accepted-job"),
        ("attempt_id", "plain" if profile == "completion" else "accepted-attempt"),
    ]
    assert result["response"] == "grounded answer"
    assert result["retrieved_chunks"] == ["retrieved original"]
    sb.table.return_value.delete.assert_called_once()
    sb.table.return_value.delete.return_value.eq.return_value.eq.assert_called_with(
        "user_id", "tenant"
    )


def test_evaluation_answer_fails_closed_and_cleans_up_on_native_failure():
    from services.rag import answer_question

    sb = MagicMock()
    with (
        patch("services.rag.get_supabase_thread_safe", return_value=sb),
        patch(
            "services.ai.chat.prepare_turn", side_effect=RuntimeError("subscription unavailable")
        ),
        pytest.raises(RuntimeError, match="subscription unavailable"),
    ):
        answer_question("question", "tenant")
    sb.table.return_value.delete.assert_called_once()
