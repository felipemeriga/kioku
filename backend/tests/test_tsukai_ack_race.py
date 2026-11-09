"""A delayed transport ACK must not overwrite authoritative domain lifecycle state."""

import copy
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.ai.chat import acknowledge_committed_turn
from services.ai.scope import ExecutionScope


def run_ack(*, during_ack=None, persisted_overrides=None, message_id="saved"):
    turn = {
        "id": "turn",
        "owner_id": "owner",
        "conversation_id": "conversation",
        "job_id": "job",
        "state": "committed",
        "assistant_message_id": "saved",
        "cancel_requested": False,
        "request": {"operation": "rag_agent", "profile": "chat"},
    }
    persisted = {**copy.deepcopy(turn), **(persisted_overrides or {})}
    writes, acknowledgements = [], []

    class Query:
        def __init__(self, table):
            self.table, self.body, self.filters = table, None, []

        def update(self, body):
            self.body = body
            return self

        def eq(self, key, value):
            self.filters.append((key, value))
            return self

        def execute(self):
            if self.table == "tsukai_chat_turns":
                writes.append((copy.deepcopy(self.body), list(self.filters)))
                if all(persisted.get(key) == value for key, value in self.filters):
                    persisted.update(self.body)
            else:
                assert self.table == "tsukai_native_usage"
            return SimpleNamespace(data=[])

    class Database:
        def table(self, name):
            return Query(name)

    class Client:
        def acknowledge(self, *args):
            acknowledgements.append(args)
            if during_ack:
                during_ack(persisted)

        def close(self):
            pass

    with (
        patch("services.ai.chat.turn_scope", return_value=ExecutionScope("owner")),
        patch("services.ai.chat.client_for", return_value=Client()),
        patch("services.ai.chat.get_supabase_thread_safe", return_value=Database()),
    ):
        acknowledge_committed_turn(turn, message_id)
    return persisted, writes, acknowledgements


def test_scope_revocation_during_remote_ack_preserves_failed_cancellation():
    def revoke(persisted):
        persisted.update(state="failed", error_code="scope_revoked", cancel_requested=True)

    persisted, writes, acknowledgements = run_ack(during_ack=revoke)

    assert acknowledgements == [("job", "backend", "saved")]
    assert persisted["state"] == "failed"
    assert persisted["error_code"] == "scope_revoked"
    assert persisted["cancel_requested"] is True
    assert persisted["assistant_message_id"] == "saved"
    assert dict(writes[0][1]) == {
        "id": "turn",
        "owner_id": "owner",
        "state": "committed",
        "assistant_message_id": "saved",
    }


@pytest.mark.parametrize(
    ("overrides", "message_id"),
    [({"owner_id": "different-owner"}, "saved"), ({}, "different-message")],
)
def test_ack_cannot_change_a_different_owner_or_publication(overrides, message_id):
    persisted, _, _ = run_ack(persisted_overrides=overrides, message_id=message_id)

    assert persisted["state"] == "committed"
    assert persisted["assistant_message_id"] == "saved"
    assert persisted["owner_id"] == overrides.get("owner_id", "owner")


def test_ack_transitions_the_matching_committed_publication():
    persisted, _, acknowledgements = run_ack()

    assert acknowledgements == [("job", "backend", "saved")]
    assert persisted["state"] == "acknowledged"
    assert persisted["assistant_message_id"] == "saved"
