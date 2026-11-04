"""Crash-window contract: durable admission can be replayed without new inference."""

import copy
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from services.ai.chat import publish_turn, submit_turn
from services.ai.client import ExecutionResult
from services.ai.scope import ExecutionScope


def test_accepted_request_lost_before_job_mapping_recovers_after_backend_restart_once():
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
            "folder_ids": [],
            "tool_allowlist": [],
        },
    }
    runner_jobs, assistant_messages = {}, []
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
