"""Crash-window contract: durable admission can be replayed without new inference."""

import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from services.ai.chat import publish_turn, submit_turn
from services.ai.client import ExecutionResult
from services.ai.scope import ExecutionScope


@pytest.mark.parametrize("ack_fails", [False, True])
def test_accepted_request_lost_before_job_mapping_recovers_after_backend_restart_once(ack_fails):
    turn = {
        "id": "turn",
        "owner_id": "owner",
        "conversation_id": "conversation",
        "job_id": None,
        "state": "prepared",
        "cancel_requested": False,
        "request": {
            "operation": "rag_agent",
            "profile": "chat",
            "idempotency_key": "turn",
            "model": "haiku",
            "prompt": "canonical input",
            "metadata": {
                "response_started_at": (
                    datetime.now(timezone.utc) - timedelta(seconds=20)
                ).isoformat()
            },
            "folder_ids": [],
            "tool_allowlist": [],
        },
    }
    runner_jobs, assistant_messages = {}, []
    saved_debug = []
    starts = []
    drop_response = [True]

    class Client:
        def submit(self, request):
            key = request["idempotency_key"]
            if key not in runner_jobs:
                runner_jobs[key] = {"request": copy.deepcopy(request), "id": "durable-job"}
                starts.append(key)
            assert runner_jobs[key]["request"] == request
            if drop_response.pop() if drop_response else False:
                raise httpx.ReadError("response lost after durable acceptance")
            return runner_jobs[key]["id"]

        def acknowledge(self, *args):
            if ack_fails:
                raise httpx.ConnectError("ACK response unavailable after domain commit")
            return None

        def close(self):
            pass

    class Query:
        def __init__(self, table=None, rpc=None, body=None):
            self.table, self.rpc, self.body = table, rpc, body
            self.update_body = None

        def update(self, body):
            self.update_body = body
            return self

        def __getattr__(self, name):
            return lambda *args, **kwargs: self

        def execute(self):
            if self.rpc == "tsukai_commit_chat_turn":
                if not assistant_messages:
                    assistant_messages.append(self.body["p_content"])
                    saved_debug.append(self.body["p_debug"])
                turn.update({"state": "committed", "assistant_message_id": "message"})
                return SimpleNamespace(data="message")
            if self.table == "tsukai_chat_turns" and self.update_body:
                turn.update(self.update_body)
            return SimpleNamespace(data=[])

    class Database:
        def table(self, name):
            return Query(table=name)

        def rpc(self, name, body):
            return Query(rpc=name, body=body)

    with (
        patch(
            "services.ai.chat.owned_turn", side_effect=lambda *args, **kwargs: copy.deepcopy(turn)
        ),
        patch("services.ai.chat.turn_scope", return_value=ExecutionScope("owner")),
        patch("services.ai.chat.client_for", side_effect=lambda *args: Client()),
        patch("services.ai.chat.get_supabase_thread_safe", return_value=Database()),
        patch("services.ai.chat.sources_for", return_value=[]),
        patch("services.ai.chat.record_job_usage", return_value=[]),
    ):
        with pytest.raises(httpx.ReadError):
            submit_turn(copy.deepcopy(turn))
        assert turn["state"] == "prepared" and turn["job_id"] is None
        # A fresh consumer instance sees only persisted domain and runner records.
        recovered = submit_turn(copy.deepcopy(turn))
        assert recovered["job_id"] == "durable-job"
        result = ExecutionResult(
            "durable-job", "canonical answer", None, None, "native", "accepted"
        )
        publish_turn(recovered, result)
        publish_turn(copy.deepcopy(turn), result)
    assert len(starts) == 1
    assert assistant_messages == ["canonical answer"]
    assert 20 <= saved_debug[0]["timings"]["total_seconds"] < 60


def test_slow_second_admission_response_cannot_regress_an_acknowledged_turn():
    turn = {
        "id": "turn",
        "owner_id": "owner",
        "conversation_id": "conversation",
        "job_id": None,
        "state": "prepared",
        "request": {
            "operation": "rag_agent",
            "profile": "chat",
            "folder_ids": [],
            "tool_allowlist": [],
        },
    }

    class Client:
        def submit(self, request):
            # The first consumer completes before this second POST returns.
            turn.update({"job_id": "job", "state": "acknowledged", "assistant_message_id": "saved"})
            return "job"

        def close(self):
            pass

    class Query:
        def __init__(self):
            self.values = None
            self.only_unmapped = False

        def update(self, values):
            self.values = values
            return self

        def eq(self, *args):
            return self

        def is_(self, key, value):
            assert (key, value) == ("job_id", "null")
            self.only_unmapped = True
            return self

        def execute(self):
            assert self.only_unmapped
            if turn["job_id"] is None:
                turn.update(self.values)
            return SimpleNamespace(data=[])

    class Database:
        def table(self, name):
            return Query()

    with (
        patch(
            "services.ai.chat.owned_turn", side_effect=lambda *args, **kwargs: copy.deepcopy(turn)
        ),
        patch("services.ai.chat.turn_scope", return_value=ExecutionScope("owner")),
        patch("services.ai.chat.client_for", return_value=Client()),
        patch("services.ai.chat.get_supabase_thread_safe", return_value=Database()),
    ):
        recovered = submit_turn(copy.deepcopy(turn))
    assert recovered["state"] == "acknowledged"
    assert recovered["assistant_message_id"] == "saved"


@pytest.mark.parametrize("code", ["conversation_policy_changed", "conversation_needs_rebuild"])
def test_pre_admission_policy_failure_emits_recovery_frame_without_job_id(code):
    import json

    from services.ai.chat import stream_turn
    from services.ai.client import ExecutionError

    with patch("services.ai.chat.submit_turn", side_effect=ExecutionError(code)):
        frames = list(stream_turn({"id": "stable-turn"}))
    payload = json.loads(frames[0].removeprefix("data: ").strip())
    assert payload["recovery_required"] is True
    assert payload["error_code"] == code
    assert payload["turn_id"] == "stable-turn"
    assert "job_id" not in payload


@pytest.mark.parametrize("code", ["conversation_policy_changed", "conversation_needs_rebuild"])
@pytest.mark.parametrize("style", ["runtime", "fastapi"])
def test_admission_conflict_preserves_typed_recovery_code_in_durable_turn(code, style):
    from unittest.mock import MagicMock

    from services.ai.client import ExecutionError

    turn = {
        "id": "turn",
        "owner_id": "owner",
        "state": "prepared",
        "job_id": None,
        "request": {"operation": "rag_agent", "profile": "chat"},
    }
    request = httpx.Request("POST", "http://runner/v1/jobs")
    body = {"error": {"code": code}} if style == "runtime" else {"detail": code}
    response = httpx.Response(409, request=request, json=body)
    client, sb = MagicMock(), MagicMock()
    client.submit.side_effect = httpx.HTTPStatusError(
        "conflict", request=request, response=response
    )
    with (
        patch("services.ai.chat.owned_turn", return_value=turn),
        patch("services.ai.chat.turn_scope", return_value=ExecutionScope("owner")),
        patch("services.ai.chat.client_for", return_value=client),
        patch("services.ai.chat.get_supabase_thread_safe", return_value=sb),
    ):
        with pytest.raises(ExecutionError, match=code):
            submit_turn(turn)
    assert sb.table.return_value.update.call_args.args[0] == {"state": "failed", "error_code": code}
