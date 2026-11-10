"""Fresh native authority reads exclude prompts without weakening revocation checks."""

import json
import time
from unittest.mock import MagicMock

import httpx
import jwt
import pytest
from fastapi import HTTPException
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

from services.ai import chat, native_tools


def projected_row():
    return {
        "id": "turn",
        "owner_id": "owner",
        "conversation_id": "conversation",
        "job_id": "job",
        "operation": "rag_agent",
        "profile": "chat",
        "folder_ids": ["folder"],
        "tool_allowlist": ["knowledge_base_search"],
        "intent": {"scope_filename": "selected.py", "content": "User question"},
    }


def fixture(monkeypatch, *, row=None, full=None):
    selected = projected_row() if row is None else row
    requests, folders = [], [{"id": "folder"}]

    def handler(request):
        requests.append(request)
        assert (
            request.url.params[
                "owner_id" if request.url.path.endswith("tsukai_chat_turns") else "user_id"
            ]
            == "eq.owner"
        )
        if request.url.path.endswith("tsukai_chat_turns"):
            assert request.url.params["job_id"] == "eq.job"
            assert request.url.params["limit"] == "1"
            return httpx.Response(
                200, json=[full if request.url.params["select"] == "*" else selected]
            )
        assert request.url.path.endswith("folders")
        return httpx.Response(200, json=folders)

    client = create_client(
        "https://projection.test.invalid",
        "nonsecret-fixture-key",
        options=SyncClientOptions(
            httpx_client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )
    monkeypatch.setattr(chat, "get_supabase_thread_safe", lambda: client)
    return requests, folders


def token(monkeypatch):
    key = "isolated-projection-fixture-key-at-least-thirty-two-bytes"
    monkeypatch.setenv("TSUKAI_CAPABILITY_KEY", key)
    return jwt.encode(
        {
            "iss": "kioku-backend",
            "aud": "kioku-native-tools",
            "iat": int(time.time()),
            "exp": int(time.time()) + 60,
            "jti": "fixture",
            "owner_id": "owner",
            "job_id": "job",
            "attempt_id": "attempt",
            "folder_ids": ["folder"],
            "tool_allowlist": ["knowledge_base_search"],
        },
        key,
        algorithm="HS256",
    )


def active_client(monkeypatch):
    client = MagicMock()
    client.active_attempt.return_value = {
        "active": True,
        "owner_id": "owner",
        "folder_ids": ["folder"],
        "tool_allowlist": ["knowledge_base_search"],
        "ai_depth": 0,
    }
    monkeypatch.setattr(native_tools, "client_for", lambda *args: client)
    return client


def test_real_postgrest_wire_projection_preserves_authority_without_prompt(monkeypatch):
    flat = projected_row()
    expected = {
        **{key: flat[key] for key in ("id", "owner_id", "conversation_id", "job_id")},
        "request": {
            **{key: flat[key] for key in ("operation", "profile", "folder_ids", "tool_allowlist")},
            "metadata": {"intent": flat["intent"]},
        },
    }
    original = {
        **expected,
        "request": {
            **expected["request"],
            "prompt": "x" * 120_000,
            "system_prompt": "private-system-marker",
        },
        "result": {"text": "previous-private-result"},
    }
    requests, _ = fixture(monkeypatch, full=original)
    assert chat.owned_turn("owner", job_id="job") == original
    result = chat.owned_turn("owner", job_id="job", authority_only=True)
    assert result == expected
    select = requests[-1].url.params["select"]
    assert "folder_ids:request->folder_ids" in select
    assert "intent:request->metadata->intent" in select
    assert "prompt" not in select and "result" not in select
    assert len(json.dumps(result)) < len(json.dumps(original)) / 100


def test_scope_revocation_is_rechecked_on_every_authentication(monkeypatch):
    requests, folders = fixture(monkeypatch)
    client = active_client(monkeypatch)
    encoded = token(monkeypatch)
    grant = native_tools.authenticate_tool(encoded)
    assert grant["scope_filename"] == "selected.py"
    assert grant["operation"] == "rag_agent"
    folders.clear()
    with pytest.raises(HTTPException) as rejected:
        native_tools.authenticate_tool(encoded)
    assert rejected.value.status_code == 403
    assert client.active_attempt.call_count == 1  # Folder revocation fails first.
    assert len(requests) == 4  # No cached turn or ownership lookup.
    assert all(request.url.params["select"] != "*" for request in requests)


def test_attempt_revocation_still_requires_fresh_live_check(monkeypatch):
    fixture(monkeypatch)
    client = active_client(monkeypatch)
    encoded = token(monkeypatch)
    native_tools.authenticate_tool(encoded)
    client.active_attempt.return_value = {"active": False}
    with pytest.raises(HTTPException) as rejected:
        native_tools.authenticate_tool(encoded)
    assert rejected.value.status_code == 403
    assert client.active_attempt.call_count == 2


@pytest.mark.parametrize(
    "field,value",
    [("intent", None), ("folder_ids", None), ("tool_allowlist", [None]), ("operation", None)],
)
def test_malformed_authority_projection_cannot_drop_scope_restrictions(monkeypatch, field, value):
    fixture(monkeypatch, row={**projected_row(), field: value})
    client = active_client(monkeypatch)
    with pytest.raises(HTTPException) as rejected:
        native_tools.authenticate_tool(token(monkeypatch))
    assert rejected.value.status_code == 403
    client.active_attempt.assert_not_called()
