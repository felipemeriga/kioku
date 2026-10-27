"""The streamed agent must finish after bounded retrieval, even if it keeps asking to search."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.rag import _run_loop_and_stream_final


class FakeStream:
    def __init__(self, number):
        self.number = number
        self.text_stream = iter(["Answer [1]"] if number == 6 else [])

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get_final_message(self):
        if self.number == 6:
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

    assert len(calls) == 6
    assert search.call_count == 4
    assert not any(t["name"] == "knowledge_base_search" for t in calls[4]["tools"])
    assert calls[5]["tools"] == []
    assert ("text_delta", "Answer [1]") in events
    assert any(
        kind == "progress" and json.loads(payload)["stage"] == "searching"
        for kind, payload in events
    )
    assert any(
        kind == "progress" and json.loads(payload)["stage"] == "generating"
        for kind, payload in events
    )
