"""Owned conversation reads disclose only accepted, currently authorized native references."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from routes.conversations import get_conversation

CONVERSATION = "a33db494-71d1-4228-8dd2-27399b22c07a"


@pytest.mark.parametrize(
    "native,job,revoked",
    [(False, "job", False), (True, None, False), (True, "job", True), (True, "job", False)],
)
@pytest.mark.parametrize(
    "state", ["submitted", "failed", "cancelled", "uncertain", "committed", "acknowledged"]
)
def test_existing_read_discovers_accepted_owned_execution_without_prompt_leak(
    native, job, revoked, state
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
            "metadata": {"intent": {"model": "sonnet", "mode": "plain"}},
        },
    }

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
            "turn_id": "turn",
            "job_id": "job",
            "conversation_id": CONVERSATION,
            "model": "sonnet",
            "mode": "plain",
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
