"""Durable completion events avoid a GET without bypassing live publication authority."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from services.ai.chat import stream_turn
from services.ai.client import ExecutionError, TsukaiClient, completed_event_result
from services.ai.scope import ExecutionScope

RESULT = {
    "text": "Canonical answer",
    "structured": {"outcome": "completed", "data": {"answer": "grounded"}},
    "usage": {"complete": True},
    "native_session_id": "native",
    "attempt_id": "attempt",
}
TURN = {
    "id": "turn",
    "owner_id": "owner",
    "conversation_id": "conversation",
    "job_id": "job",
    "request": {"operation": "rag_agent", "profile": "chat", "model": "haiku"},
}


def event(result=RESULT):
    return {
        "job_id": "job",
        "type": "job.completed",
        "seq": 1,
        "attempt_id": "attempt",
        "data": {"result": copy.deepcopy(result), "error": None},
    }


def get_result(result):
    with_client = TsukaiClient(
        "http://tsukai",
        "service",
        "grant",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"job_id": "job", "status": "completed", "result": result}
            )
        ),
    )
    try:
        return with_client.result("job")
    finally:
        with_client.close()


def test_event_and_get_share_the_canonical_result_contract():
    assert completed_event_result("job", event()) == get_result(RESULT)


@pytest.mark.parametrize(
    "changes",
    [
        {"text": 5},
        {"usage": []},
        {"structured": []},
        {"native_session_id": {}},
        {"attempt_id": []},
        {"structured": {"outcome": "needs_input", "data": None}},
        {"structured": {"outcome": "failed", "data": None}},
        {"structured": {"outcome": "completed", "data": None}},
        {"structured": {"outcome": {}, "data": {}}},
    ],
)
def test_event_and_get_reject_the_same_malformed_or_unpublishable_results(changes):
    result = {**copy.deepcopy(RESULT), **changes}
    with pytest.raises(ExecutionError) as from_event:
        completed_event_result("job", event(result))
    with pytest.raises(ExecutionError) as from_get:
        get_result(result)
    assert from_event.value.code == from_get.value.code


@pytest.mark.parametrize(
    "changes",
    [
        {"job_id": "foreign"},
        {"type": "job.failed"},
        {"attempt_id": "foreign"},
        {"attempt_id": None},
        {"data": None},
        {"data": {"result": None}},
        {"data": {"result": RESULT, "error": {"code": "failed"}}},
    ],
)
def test_present_foreign_or_malformed_events_never_fall_back(changes):
    with pytest.raises(ExecutionError):
        completed_event_result("job", {**event(), **changes})


class Query:
    def __init__(self, table):
        self.table = table

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: self

    def execute(self):
        return SimpleNamespace(
            data={"debug": {}, "citations": []} if self.table == "messages" else []
        )


class Database:
    def __init__(self):
        self.commits = []

    def table(self, name):
        return Query(name)

    def rpc(self, name, body):
        self.commits.append((name, body))
        raise AssertionError("publication must not reach commit after revoked native usage read")


@pytest.mark.parametrize("legacy_kind", [None, "job.completed", "replay.expired"])
def test_stream_uses_event_payload_or_legacy_get_as_required(legacy_kind):
    terminal = event()
    if legacy_kind:
        terminal["type"] = legacy_kind
        terminal["data"] = (
            {}
            if legacy_kind == "job.completed"
            else {"result": {"text": "legacy", "structured": None}}
        )
    client = MagicMock()
    client.events.return_value = iter([terminal])
    canonical = get_result(RESULT)
    client.result.return_value = canonical
    with (
        patch("services.ai.chat.submit_turn", return_value=TURN),
        patch("services.ai.chat.turn_scope", return_value=ExecutionScope("owner")),
        patch("services.ai.chat.client_for", return_value=client),
        patch("services.ai.chat.get_supabase_thread_safe", return_value=Database()),
        patch("services.ai.chat.publish_turn", return_value="saved") as publish,
    ):
        frames = list(stream_turn(TURN))
    publish.assert_called_once_with(TURN, canonical, attempt_id="attempt", defer_ack=True)
    if legacy_kind:
        client.result.assert_called_once_with("job")
    else:
        client.result.assert_not_called()
    done = json.loads(frames[-1].removeprefix("data: ").strip())
    assert done["done"] and done["replace"] == RESULT["text"]


@pytest.mark.parametrize("status", [403, 410])
def test_native_revocation_or_tombstone_during_usage_blocks_domain_publication(status):
    requests = []

    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith("/events"):
            return httpx.Response(200, text="data: " + json.dumps(event()) + "\n\n")
        assert request.url.path.endswith("/usage"), "no redundant canonical-result GET"
        return httpx.Response(status, json={"detail": "execution_scope_deleted"})

    def client_for(*_args):
        return TsukaiClient(
            "http://tsukai", "service", "grant", transport=httpx.MockTransport(handler)
        )

    database = Database()
    with (
        patch("services.ai.chat.submit_turn", return_value=TURN),
        patch("services.ai.chat.turn_scope", return_value=ExecutionScope("owner")),
        patch("services.ai.chat.client_for", side_effect=client_for),
        patch("services.ai.chat.get_supabase_thread_safe", return_value=database),
        patch("services.ai.chat.sources_for", return_value=[]),
        patch("services.ai.chat.wake_reconciliation") as wake,
    ):
        frames = list(stream_turn(TURN))
    assert requests == ["/v1/jobs/job/events", "/v1/jobs/job/usage"]
    assert not database.commits
    wake.assert_not_called()
    payloads = [json.loads(frame.removeprefix("data: ").strip()) for frame in frames]
    assert any("error" in payload for payload in payloads)
    assert not any(payload.get("done") or "replace" in payload for payload in payloads)


@pytest.mark.parametrize(
    "changes",
    [
        {"job_id": "foreign"},
        {"attempt_id": "foreign"},
        {"data": {"result": None}},
    ],
)
def test_corrupt_stream_completion_never_fetches_or_commits_another_result(changes):
    client = MagicMock()
    client.events.return_value = iter([{**event(), **changes}])
    with (
        patch("services.ai.chat.submit_turn", return_value=TURN),
        patch("services.ai.chat.turn_scope", return_value=ExecutionScope("owner")),
        patch("services.ai.chat.client_for", return_value=client),
        patch("services.ai.chat.publish_turn") as publish,
    ):
        frames = list(stream_turn(TURN))
    client.result.assert_not_called()
    publish.assert_not_called()
    assert "error" in json.loads(frames[-1].removeprefix("data: ").strip())


def test_legacy_get_rejects_a_conflicting_event_attempt():
    terminal = {**event(), "data": {}, "attempt_id": "different-attempt"}
    client = MagicMock()
    client.events.return_value = iter([terminal])
    client.result.return_value = get_result(RESULT)
    with (
        patch("services.ai.chat.submit_turn", return_value=TURN),
        patch("services.ai.chat.turn_scope", return_value=ExecutionScope("owner")),
        patch("services.ai.chat.client_for", return_value=client),
        patch("services.ai.chat.publish_turn") as publish,
    ):
        frames = list(stream_turn(TURN))
    client.result.assert_called_once_with("job")
    publish.assert_not_called()
    assert "attempt_mismatch" in frames[-1]
