from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from services.ai.models import chat_models, chat_operation, resolve_native_model


def catalog():
    return {
        "schema_version": 1,
        "models": [
            {
                "value": alias,
                "resolvedModel": model,
                "displayName": alias,
                "requires_usage_credits": paid,
                "selectable": not paid,
            }
            for alias, model, paid in [
                ("sonnet", "claude-sonnet-current", False),
                ("haiku", "claude-haiku-current", False),
                ("opus", "claude-opus-current", False),
                ("fable", "claude-fable-current", True),
            ]
        ],
    }


def test_api_users_never_access_native_catalog_or_inject_provider_models():
    with (
        patch("services.ai.models.engine_for", return_value="api"),
        patch("services.ai.models.client_for") as client,
    ):
        assert chat_models("other-owner") == {"engine": "api", "models": []}
        assert chat_operation("sonnet", "other-owner") == "rag_agent_sonnet"
        assert chat_operation("haiku", "other-owner") == "rag_agent"
        with pytest.raises(HTTPException) as error:
            chat_operation("claude-opus-current", "other-owner")
        assert error.value.status_code == 422
        client.assert_not_called()


def test_authenticated_api_route_keeps_other_owners_on_legacy_models(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth import get_current_user
    from routes.chat import router

    monkeypatch.setenv("TSUKAI_CREDENTIAL_OWNER_ID", "native-owner")
    monkeypatch.setenv("TSUKAI_NATIVE_TASKS", "rag_agent,rag_agent_sonnet")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: "other-owner"
    db = MagicMock()
    query = db.table.return_value
    for method in ("select", "eq", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value.data = [{"id": "owned"}]
    with (
        TestClient(app) as http,
        patch("routes.chat.get_supabase", return_value=db),
        patch("services.ai.models.client_for") as native_client,
        patch("routes.chat.stream_rag_response", return_value=iter([])) as api_stream,
    ):
        assert http.get("/api/chat/models").json() == {"engine": "api", "models": []}
        request = {"conversation_id": "11111111-1111-4111-8111-111111111111", "content": "question"}
        assert (
            http.post("/api/chat", json={**request, "model": "claude-opus-current"}).status_code
            == 422
        )
        assert http.post("/api/chat", json={**request, "model": "sonnet"}).status_code == 200
        assert api_stream.call_args.kwargs["model"] == "sonnet"
        native_client.assert_not_called()


def test_owner_catalog_uses_metadata_only_owner_capability_and_closes_client():
    client = MagicMock()
    client.models.return_value = catalog()
    with (
        patch("services.ai.models.native_enabled", return_value=True),
        patch("services.ai.models.client_for", return_value=client) as factory,
    ):
        result = chat_models("owner")
    assert result["engine"] == "tsukai"
    scope, operation, profile = factory.call_args.args
    assert scope.owner_id == "owner" and not scope.admin and not scope.folder_ids
    assert operation == "runtime.models.read" and profile is None
    client.models.assert_called_once()
    client.submit.assert_not_called()
    client.close.assert_called_once()


@pytest.mark.parametrize(
    "selected,resolved",
    [
        ("haiku", "claude-haiku-current"),
        ("sonnet", "claude-sonnet-current"),
        ("claude-opus-current", "claude-opus-current"),
    ],
)
def test_native_model_resolves_only_catalog_choices(selected, resolved):
    with patch("services.ai.models.chat_models", return_value=catalog()):
        assert resolve_native_model(selected, "owner") == resolved


@pytest.mark.parametrize("selected", ["arbitrary-provider-id", "opus", "claude-fable-current"])
def test_unknown_aliases_and_extra_credit_models_are_rejected(selected):
    with patch("services.ai.models.chat_models", return_value=catalog()):
        with pytest.raises(HTTPException) as error:
            resolve_native_model(selected, "owner")
        assert error.value.status_code == 422


def test_stale_or_unavailable_catalog_cannot_admit_new_models():
    with patch("services.ai.models.chat_models", return_value={**catalog(), "stale": True}):
        with pytest.raises(HTTPException) as error:
            resolve_native_model("claude-opus-current", "owner")
        assert error.value.status_code == 503
    with patch("services.ai.models.chat_models", side_effect=HTTPException(503, "unavailable")):
        with pytest.raises(HTTPException):
            resolve_native_model("claude-opus-current", "owner")
        assert resolve_native_model("haiku", "owner").startswith("claude-haiku-")


def test_durable_same_turn_replay_does_not_revalidate_or_change_its_accepted_model():
    from services.ai.chat import prepare_turn

    intent = {
        "content": "question",
        "model": "claude-opus-current",
        "mode": "deep",
        "scope_folder_id": None,
        "scope_filename": None,
        "rebuild": False,
    }
    existing = {
        "conversation_id": "conversation",
        "request": {"metadata": {"intent": intent}, "model": "claude-opus-current"},
    }
    db = MagicMock()
    query = db.table.return_value
    for method in ("select", "eq", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value.data = [existing]
    resolver = MagicMock(side_effect=HTTPException(503, "catalog unavailable"))
    with patch("services.ai.chat.get_supabase_thread_safe", return_value=db):
        assert (
            prepare_turn(
                owner_id="owner",
                conversation_id="conversation",
                content="question",
                turn_id="turn",
                model="claude-opus-current",
                mode="deep",
                folder_id=None,
                filename=None,
                model_resolver=resolver,
            )
            is existing
        )
    resolver.assert_not_called()


@pytest.mark.parametrize("mode", ["plain", "agentic", "deep"])
def test_actual_selected_id_reaches_native_completion_and_agent_policy(mode):
    from services.ai.chat import prepare_turn

    db = MagicMock()
    query = db.table.return_value
    for method in ("select", "eq", "limit", "order"):
        getattr(query, method).return_value = query
    query.execute.return_value.data = []
    db.rpc.side_effect = lambda _name, args: MagicMock(
        execute=lambda: MagicMock(data={"request": args["p_request"]})
    )
    resolver = MagicMock(return_value="claude-opus-current")
    with (
        patch("services.ai.chat.get_supabase_thread_safe", return_value=db),
        patch("services.ai.chat.descendant_folder_ids", return_value=["folder"]),
        patch("services.ai.chat.execute_tool", return_value="evidence"),
        patch("services.ai.chat.save_trace"),
    ):
        turn = prepare_turn(
            owner_id="owner",
            conversation_id="conversation",
            content="question",
            turn_id="turn",
            model="claude-opus-current",
            mode=mode,
            folder_id="folder",
            filename=None,
            model_resolver=resolver,
        )
    request = turn["request"]
    assert request["model"] == "claude-opus-current"
    assert request["metadata"]["requested_model_id"] == request["model"]
    assert request["profile"] == ("completion" if mode == "plain" else "chat")
    assert request["thinking_tokens"] == (2048 if mode == "deep" else 0)
    resolver.assert_called_once_with("claude-opus-current")


def test_effort_capabilities_survive_catalog_and_unsupported_level_is_rejected():
    value = catalog()
    value["models"][0].update(supportsEffort=True, supportedEffortLevels=["low", "high"])
    client = MagicMock()
    client.models.return_value = value
    with (
        patch("services.ai.models.native_enabled", return_value=True),
        patch("services.ai.models.client_for", return_value=client),
    ):
        exposed = chat_models("owner")
    assert exposed["models"][0]["supportedEffortLevels"] == ["low", "high"]
    with patch("services.ai.models.chat_models", return_value=exposed):
        assert resolve_native_model("sonnet", "owner", "low") == "claude-sonnet-current"
        with pytest.raises(HTTPException) as error:
            resolve_native_model("sonnet", "owner", "medium")
        assert error.value.status_code == 422
