"""The streamed agent must finish after bounded retrieval, even if it keeps asking to search."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.rag import _run_loop_and_stream_final


class FakeStream:
    def __init__(self, number):
        self.number = number
        self.text_stream = iter(["Answer [1]"] if number == 5 else ["I'll investigate now."])

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get_final_message(self):
        if self.number == 5:
            return SimpleNamespace(stop_reason="end_turn", content=[], usage=None)
        block = SimpleNamespace(
            type="tool_use",
            id=f"search-{self.number}",
            name="knowledge_base_search",
            input={"query": f"question {self.number}"},
        )
        return SimpleNamespace(stop_reason="tool_use", content=[block], usage=None)


def test_streamed_agent_bounds_searches_and_forces_final_answer():
    calls = []

    def fake_stream(**kwargs):
        calls.append(kwargs)
        return FakeStream(len(calls))

    citations = MagicMock()
    citations.entries.return_value = []
    with (
        patch("services.rag.stream_complete", side_effect=fake_stream),
        patch("services.rag.execute_tool", return_value="Relevant source [1]") as search,
        patch("services.rag.CitationRegistry", return_value=citations),
        patch("services.rag.get_supabase_thread_safe"),
    ):
        events = list(
            _run_loop_and_stream_final(
                user_message="How does it work?",
                user_id="user",
                model="sonnet",
                mode="deep",
                history=[],
            )
        )

    assert len(calls) == 5
    assert search.call_count == 4
    assert calls[4]["tools"] == []
    assert calls[4]["thinking_budget"] is None
    assert "Answer my original question now" in calls[4]["messages"][-1]["content"]
    assert ("text_delta", "Answer [1]") in events
    assert not any("investigate" in payload for kind, payload in events if kind == "text_delta")
    assert any(
        kind == "progress" and json.loads(payload)["stage"] == "searching"
        for kind, payload in events
    )
    assert any(
        kind == "progress" and json.loads(payload)["stage"] == "generating"
        for kind, payload in events
    )


def test_empty_final_round_gets_a_fallback_answer():
    calls = []

    def fake_stream(**kwargs):
        calls.append(kwargs)
        stream = FakeStream(len(calls))
        if len(calls) == 2:
            stream.text_stream = iter([])
        return stream

    with (
        patch("services.rag._MAX_SEARCHES_PER_TURN", 1),
        patch("services.rag.stream_complete", side_effect=fake_stream),
        patch(
            "services.rag.complete",
            return_value=SimpleNamespace(
                content=[SimpleNamespace(type="text", text="Grounded answer [1]")], usage=None
            ),
        ) as fallback,
        patch("services.rag.execute_tool", return_value="Relevant source [1]"),
        patch("services.rag.CitationRegistry", return_value=MagicMock(entries=lambda: [])),
        patch("services.rag.get_supabase_thread_safe"),
    ):
        events = list(
            _run_loop_and_stream_final(
                user_message="How does it work?",
                user_id="user",
                model="sonnet",
                mode="deep",
                history=[],
            )
        )

    assert len(calls) == 2
    assert calls[1]["tools"] == []
    fallback.assert_called_once()
    assert ("text_delta", "Grounded answer [1]") in events


def test_final_answer_strips_literal_thinking_block():
    class FinalStream(FakeStream):
        def __init__(self):
            self.text_stream = iter(
                ["<thinking>Let me research.", "</thinking>\n# Answer\nIt works [1]."]
            )

        def get_final_message(self):
            return SimpleNamespace(stop_reason="end_turn", content=[], usage=None)

    with (
        patch("services.rag._MAX_TOOL_ROUNDS", 0),
        patch("services.rag.stream_complete", return_value=FinalStream()),
        patch("services.rag.CitationRegistry", return_value=MagicMock(entries=lambda: [])),
        patch("services.rag.get_supabase_thread_safe"),
    ):
        events = list(
            _run_loop_and_stream_final(
                user_message="How does it work?",
                user_id="user",
                model="sonnet",
                mode="deep",
                history=[],
            )
        )

    assert ("text_delta", "# Answer\nIt works [1].") in events
    assert not any("Let me research" in payload for kind, payload in events if kind == "text_delta")
