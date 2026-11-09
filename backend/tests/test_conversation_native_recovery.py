"""Owned conversation reads disclose only accepted, currently authorized native references."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from routes.conversations import get_conversation

CONVERSATION = "a33db494-71d1-4228-8dd2-27399b22c07a"


@pytest.mark.parametrize("mode,effort", [("plain", None), ("deep", None), ("agentic", "medium")])
@pytest.mark.parametrize(
    "native,job,revoked",
    [(False, "job", False), (True, None, False), (True, "job", True), (True, "job", False)],
)
@pytest.mark.parametrize(
    "state", ["submitted", "failed", "cancelled", "uncertain", "committed", "acknowledged"]
)
def test_existing_read_discovers_accepted_owned_execution_without_prompt_leak(
    native, job, revoked, state, mode, effort
):
    db = MagicMock()
    queries = {}
    turn = {
        "state": state,
        "id": "turn",
        "job_id": job,
        "owner_id": "owner",
        "conversation_id": CONVERSATION,
        "request": {
            "prompt": "private prompt",
            "metadata": {"intent": {"model": "sonnet", "mode": mode}},
        },
    }

    if effort is not None:
        turn["request"]["metadata"]["intent"]["reasoning_effort"] = effort

    def table(name):
        q = MagicMock()
        for method in ("select", "eq", "order", "in_", "limit"):
            getattr(q, method).return_value = q
        q.not_.is_.return_value = q
        q.execute.return_value = SimpleNamespace(
            data={
                "conversations": [{"id": CONVERSATION}],
                "messages": [],
                "tsukai_chat_turns": [turn],
            }[name]
        )
        queries[name] = q
        return q

    db.table.side_effect = table
    with (
        patch("routes.conversations.get_supabase", return_value=db),
        patch("services.ai.registry.engine_for", return_value="tsukai" if native else "api"),
        patch(
            "services.ai.chat.turn_scope", side_effect=HTTPException(403) if revoked else None
        ) as scope,
    ):
        result = get_conversation(CONVERSATION, "owner")
    assert "private prompt" not in str(result)
    if native:
        queries["tsukai_chat_turns"].not_.is_.assert_called_once_with("job_id", "null")
        queries["tsukai_chat_turns"].eq.assert_any_call("owner_id", "owner")
        queries["tsukai_chat_turns"].eq.assert_any_call("conversation_id", CONVERSATION)
    else:
        assert "tsukai_chat_turns" not in queries
    if native and job and not revoked and state not in {"committed", "acknowledged"}:
        assert result["active_execution"] == {
            "state": state,
            "user_message_id": None,
            "scope_folder_id": None,
            "scope_filename": None,
            "turn_id": "turn",
            "job_id": "job",
            "conversation_id": CONVERSATION,
            "model": "sonnet",
            "mode": mode,
            "reasoning_effort": effort or ("high" if mode == "deep" else "low"),
        }
        scope.assert_called_once_with(turn)
    else:
        assert result["active_execution"] is None


def test_foreign_conversation_cannot_query_execution_reference():
    db = MagicMock()
    query = db.table.return_value.select.return_value
    query.eq.return_value.eq.return_value.execute.return_value.data = []
    with (
        patch("routes.conversations.get_supabase", return_value=db),
        patch("services.ai.registry.engine_for") as engine,
    ):
        with pytest.raises(HTTPException) as error:
            get_conversation(CONVERSATION, "foreign")
    assert error.value.status_code == 404
    engine.assert_not_called()


@pytest.mark.parametrize("visible_on_reread", [True, False])
def test_publication_between_message_and_turn_reads_never_loses_answer_or_replay(visible_on_reread):
    db = MagicMock()
    turn = {
        "id": "turn",
        "job_id": "job",
        "state": "committed",
        "owner_id": "owner",
        "conversation_id": CONVERSATION,
        "assistant_message_id": "answer",
        "user_message_id": "question",
        "request": {"metadata": {"intent": {"model": "sonnet", "mode": "plain"}}},
    }
    message_reads = []

    def table(name):
        q = MagicMock()
        for method in ("select", "eq", "order", "limit"):
            getattr(q, method).return_value = q
        q.not_.is_.return_value = q

        def execute():
            if name == "conversations":
                return SimpleNamespace(data=[{"id": CONVERSATION}])
            if name == "tsukai_chat_turns":
                return SimpleNamespace(data=[turn])
            message_reads.append(True)
            return SimpleNamespace(
                data=[{"id": "answer", "role": "assistant", "content": "canonical"}]
                if len(message_reads) > 1 and visible_on_reread
                else [{"id": "question", "role": "user", "content": "original"}]
            )

        q.execute.side_effect = execute
        return q

    db.table.side_effect = table
    with (
        patch("routes.conversations.get_supabase", return_value=db),
        patch("services.ai.registry.engine_for", return_value="tsukai"),
        patch("services.ai.chat.turn_scope"),
    ):
        result = get_conversation(CONVERSATION, "owner")
    assert len(message_reads) == 2
    if visible_on_reread:
        assert result["messages"][0]["id"] == "answer"
        assert result["active_execution"] is None
    else:
        assert result["active_execution"]["job_id"] == "job"
        assert result["active_execution"]["state"] == "committed"


def test_admission_between_reads_hydrates_exact_accepted_user_for_explicit_recovery():
    db = MagicMock()
    turn = {
        "id": "turn",
        "job_id": "job",
        "state": "uncertain",
        "owner_id": "owner",
        "user_message_id": "accepted-user",
        "conversation_id": CONVERSATION,
        "request": {
            "metadata": {
                "intent": {
                    "model": "sonnet",
                    "mode": "plain",
                    "scope_folder_id": "folder",
                    "scope_filename": "guide.md",
                }
            }
        },
    }
    reads = []

    def table(name):
        q = MagicMock()
        for method in ("select", "eq", "order", "limit"):
            getattr(q, method).return_value = q
        q.not_.is_.return_value = q

        def execute():
            if name == "conversations":
                return SimpleNamespace(data=[{"id": CONVERSATION}])
            if name == "tsukai_chat_turns":
                return SimpleNamespace(data=[turn])
            reads.append(True)
            return SimpleNamespace(
                data=[]
                if len(reads) == 1
                else [{"id": "accepted-user", "role": "user", "content": "original"}]
            )

        q.execute.side_effect = execute
        return q

    db.table.side_effect = table
    with (
        patch("routes.conversations.get_supabase", return_value=db),
        patch("services.ai.registry.engine_for", return_value="tsukai"),
        patch("services.ai.chat.turn_scope"),
    ):
        result = get_conversation(CONVERSATION, "owner")
    assert len(reads) == 2
    assert result["messages"][0]["id"] == result["active_execution"]["user_message_id"]
    assert result["active_execution"]["scope_folder_id"] == "folder"
    assert result["active_execution"]["scope_filename"] == "guide.md"


@pytest.mark.parametrize("rejected", [True, False])
def test_read_collapses_only_confirmed_unstarted_rejected_retry(rejected):
    db = MagicMock()
    messages = [
        {"id": "saved", "role": "assistant", "content": "Saved answer"},
        {"id": "rejected", "role": "user", "content": "Follow up"},
        {"id": "retry", "role": "user", "content": "Follow up"},
    ]
    queries = {}

    def table(name):
        q = MagicMock()
        for method in ("select", "eq", "order", "is_", "in_"):
            getattr(q, method).return_value = q
        q.execute.return_value = SimpleNamespace(
            data={
                "conversations": [{"id": CONVERSATION}],
                "messages": messages,
                "tsukai_chat_turns": [{"user_message_id": "rejected"}] if rejected else [],
            }[name]
        )
        queries[name] = q
        return q

    db.table.side_effect = table
    with (
        patch("routes.conversations.get_supabase", return_value=db),
        patch("services.ai.registry.engine_for", return_value="api"),
    ):
        result = get_conversation(CONVERSATION, "owner")
    assert [m["id"] for m in result["messages"]] == (
        ["saved", "retry"] if rejected else ["saved", "rejected", "retry"]
    )
    q = queries["tsukai_chat_turns"]
    q.eq.assert_any_call("owner_id", "owner")
    q.eq.assert_any_call("conversation_id", CONVERSATION)
    q.eq.assert_any_call("state", "failed")
    q.eq.assert_any_call("error_code", "conversation_policy_changed")
    q.is_.assert_called_once_with("job_id", "null")
