"""Plain native generation must not inherit impossible agentic search instructions."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.ai.chat import NATIVE_PLAIN_PROMPT, prepare_turn
from services.rag import SYSTEM_PROMPT


@pytest.mark.parametrize("mode", ["plain", "agentic", "deep"])
def test_native_mode_contract_matches_real_tool_availability_with_missing_facts(mode):
    # The actual browser failure asked for modes/dry-run absent from its supplied guide.
    question = "Explain output modes and dry-run in 250 words."
    evidence = "[1] This guide documents validation rules. No output modes or dry-run evidence."
    db = MagicMock()
    query = db.table.return_value
    for method in ("select", "eq", "limit", "order"):
        getattr(query, method).return_value = query
    query.execute.return_value.data = []
    db.rpc.side_effect = lambda name, body: SimpleNamespace(
        execute=lambda: SimpleNamespace(data={"request": body["p_request"]})
    )
    with (
        patch("services.ai.chat.get_supabase_thread_safe", return_value=db),
        patch("services.ai.chat.descendant_folder_ids", return_value=["folder"]),
        patch("services.ai.chat.execute_tool", return_value=evidence) as retrieve,
        patch("services.ai.chat.save_trace"),
    ):
        turn = prepare_turn(
            owner_id="owner",
            conversation_id="conversation",
            content=question,
            turn_id="turn",
            model="haiku",
            mode=mode,
            folder_id="folder",
            filename="guide.md",
        )
    request = turn["request"]
    prompt = json.loads(request["prompt"])
    assert prompt["user_message"] == question
    retrieve.assert_called_once()
    assert retrieve.call_args.kwargs["scope_filename"] == "guide.md"
    if mode == "plain":
        assert request["profile"] == "completion"
        assert request["tool_allowlist"] == []
        assert prompt["evidence"] == evidence
        assert request["system_prompt"] == NATIVE_PLAIN_PROMPT
        assert "No tools are available" in request["system_prompt"]
        assert "Do not claim you searched" in request["system_prompt"]
        assert "recall user-provided details from conversation history" in request["system_prompt"]
        assert "simulate tool calls" in request["system_prompt"]
        assert "do not establish a requested fact" in request["system_prompt"]
        assert "Call knowledge_base_search" not in request["system_prompt"]
        assert "## How to work (agentic)" not in request["system_prompt"]
    else:
        assert request["profile"] == "chat"
        assert "knowledge_base_search" in request["tool_allowlist"]
        assert request["system_prompt"].startswith(SYSTEM_PROMPT)
        assert prompt["current_turn_evidence"] == evidence
