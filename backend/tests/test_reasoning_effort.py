"""Effort is validated before admission and part of immutable turn intent."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from routes.chat import ChatRequest
from services.ai.chat import prepare_turn
from services.rag import _agent_params


def test_new_chat_defaults_to_low_with_tools():
    request = ChatRequest(conversation_id="conversation", content="recall")
    assert request.reasoning_effort == "low"
    assert request.mode == "agentic"


@pytest.mark.parametrize("invalid", ["", "max", "LOW", 1, {}, None])
def test_effort_rejects_unsupported_values(invalid):
    with pytest.raises(ValidationError):
        ChatRequest(conversation_id="conversation", content="recall", reasoning_effort=invalid)


@pytest.mark.parametrize("effort,budget", [("low", None), ("medium", 2048), ("high", 4096)])
def test_api_path_honors_explicit_effort_independently_of_mode(effort, budget):
    assert _agent_params("haiku", "agentic", effort)[1:] == (8192, budget)
    assert _agent_params("haiku", "deep", effort)[1:] == (8192, budget)


@pytest.mark.parametrize("legacy", [False, True])
def test_frozen_turn_replay_never_reinterprets_old_effort(legacy):
    intent = dict(
        content="recall",
        model="haiku",
        mode="deep",
        scope_folder_id=None,
        scope_filename=None,
        rebuild=False,
    )
    if not legacy:
        intent["reasoning_effort"] = "high"
    turn = {"conversation_id": "conversation", "request": {"metadata": {"intent": intent}}}
    db = MagicMock()
    query = db.table.return_value.select.return_value
    query.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [turn]
    kwargs = dict(
        owner_id="owner",
        conversation_id="conversation",
        content="recall",
        turn_id="turn",
        model="haiku",
        mode="deep",
        folder_id=None,
        filename=None,
    )
    with patch("services.ai.chat.get_supabase_thread_safe", return_value=db):
        if legacy:
            assert prepare_turn(**kwargs, reasoning_effort="low", legacy_effort_retry=True) == turn
        else:
            assert prepare_turn(**kwargs, reasoning_effort="high") == turn
        with pytest.raises(HTTPException) as error:
            prepare_turn(**kwargs, reasoning_effort="low")
        assert error.value.status_code == 409


@pytest.mark.parametrize(
    "mode,fields,api_expected,native_expected",
    [
        ("deep", {}, None, "high"),
        ("agentic", {}, None, "low"),
        ("deep", {"reasoning_effort": "low"}, "low", "low"),
        ("deep", {"reasoning_effort": "medium"}, "medium", "medium"),
    ],
)
@pytest.mark.parametrize("engine", ["api", "tsukai"])
def test_legacy_deep_and_explicit_overrides_survive_both_routes(
    mode, fields, api_expected, native_expected, engine
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth import get_current_user
    from routes.chat import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "owner"
    db = MagicMock()
    query = db.table.return_value.select.return_value
    query.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "owned"}
    ]
    with (
        TestClient(app) as http,
        patch("routes.chat.get_supabase", return_value=db),
        patch("routes.chat.engine_for", return_value=engine),
        patch("routes.chat.stream_rag_response", return_value=iter([])) as api_stream,
        patch("services.ai.chat.prepare_turn", return_value={"id": "turn"}) as prepare,
        patch("services.ai.chat.stream_turn", return_value=iter([])),
        patch("services.ai.chat.wake_reconciliation"),
    ):
        r = http.post(
            "/api/chat",
            json={
                "conversation_id": "11111111-1111-4111-8111-111111111111",
                "turn_id": "22222222-2222-4222-8222-222222222222",
                "content": "recall",
                "mode": mode,
                **fields,
            },
        )
        assert r.status_code == 200
        if engine == "api":
            assert api_stream.call_args.kwargs["reasoning_effort"] == api_expected
            prepare.assert_not_called()
        else:
            assert prepare.call_args.kwargs["reasoning_effort"] == native_expected
            api_stream.assert_not_called()
