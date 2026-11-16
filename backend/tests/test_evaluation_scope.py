import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

from services import evaluation, scope


def scoped_db(monkeypatch):
    rows = [
        {"id": "allowed", "user_id": "owner", "parent_id": None},
        {"id": "child", "user_id": "owner", "parent_id": "allowed"},
        {"id": "sibling", "user_id": "owner", "parent_id": None},
        {"id": "foreign", "user_id": "other", "parent_id": None},
        {"id": "foreign-child", "user_id": "other", "parent_id": "allowed"},
    ]

    def handler(request):
        assert request.url.path.endswith("/folders")
        params = request.url.params
        assert params["user_id"] == "eq.owner"
        selected = [r for r in rows if r["user_id"] == "owner"]
        if "id" in params:
            selected = [r for r in selected if "eq." + r["id"] == params["id"]]
        if "parent_id" in params:
            parents = params["parent_id"].removeprefix("in.(").removesuffix(")").split(",")
            selected = [r for r in selected if r["parent_id"] in parents]
        return httpx.Response(200, json=selected)

    client = create_client(
        "https://scope.test.invalid",
        "test-only",
        options=SyncClientOptions(
            httpx_client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )
    monkeypatch.setattr(scope, "get_supabase", lambda: client)
    monkeypatch.setattr(evaluation, "get_supabase_thread_safe", lambda: client)


def fake_ai(monkeypatch):
    calls = []
    monkeypatch.setattr(evaluation, "_get_ragas_llm", lambda: object())
    monkeypatch.setattr(evaluation, "VoyageEmbeddings", lambda: object())

    def answer(**kwargs):
        calls.append(kwargs)
        return {"response": "safe answer", "retrieved_chunks": []}

    class Scores:
        iloc = [SimpleNamespace(to_dict=lambda: {})]

        def __len__(self):
            return 1

    monkeypatch.setattr(evaluation, "answer_question", answer)
    monkeypatch.setattr(
        evaluation,
        "evaluate",
        lambda **_: SimpleNamespace(_repr_dict={}, to_pandas=lambda: Scores()),
    )
    return calls


def test_evaluation_scopes_every_agent_question_to_owned_subtree(monkeypatch):
    scoped_db(monkeypatch)
    calls = fake_ai(monkeypatch)
    result = asyncio.run(
        evaluation.evaluate_rag_pipeline(
            [{"question": "confidential sibling data"}], "owner", "allowed"
        )
    )
    assert result["details"][0]["response"] == "safe answer"
    assert calls[0]["scope_folder_ids"] == ["allowed", "child"]
    assert calls[0]["user_id"] == "owner"


@pytest.mark.parametrize("folder", ["foreign", "missing"])
def test_invalid_scope_denied_before_any_ai_calls(monkeypatch, folder):
    scoped_db(monkeypatch)
    for name in ("_get_ragas_llm", "VoyageEmbeddings", "answer_question", "evaluate"):
        monkeypatch.setattr(evaluation, name, lambda *a, **k: pytest.fail("AI called before auth"))
    with pytest.raises(HTTPException) as error:
        asyncio.run(evaluation.evaluate_rag_pipeline([{"question": "question"}], "owner", folder))
    assert error.value.status_code == 404


def test_owner_authenticated_unscoped_evaluation_remains_available(monkeypatch):
    calls = fake_ai(monkeypatch)
    asyncio.run(evaluation.evaluate_rag_pipeline([{"question": "question"}], "owner"))
    assert calls[0]["scope_folder_ids"] is None


def test_mcp_evaluation_fails_closed_without_folder_scope(monkeypatch):
    import mcp_server

    async def forbidden(**kwargs):
        pytest.fail("Unscoped MCP evaluation dispatched")

    monkeypatch.setattr(mcp_server, "evaluate_rag_pipeline", forbidden)
    user_token = mcp_server._current_user_id.set("owner")
    scope_token = mcp_server._current_scope_folder_id.set(None)
    try:
        assert asyncio.run(mcp_server.evaluate_retrieval("question")) == "Error: Not authenticated."
    finally:
        mcp_server._current_user_id.reset(user_token)
        mcp_server._current_scope_folder_id.reset(scope_token)
