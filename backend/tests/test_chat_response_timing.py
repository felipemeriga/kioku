"""Timing must be streamed and persisted even without debug, never for partial errors."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.rag import stream_rag_response


@pytest.mark.parametrize("failed", [False, True])
def test_api_completion_timing_survives_reload_without_debug(failed):
    rows = []

    class Query:
        def insert(self, row):
            rows.append(row)
            return self

        def __getattr__(self, _):
            return lambda *a, **kw: self

        def execute(self):
            return SimpleNamespace(data=[])

    class DB:
        def table(self, _):
            return Query()

    def generate(**_):
        yield "text_delta", "Answer"
        if failed:
            yield "error", "interrupted"

    with (
        patch("services.rag.get_supabase_thread_safe", return_value=DB()),
        patch("services.rag._run_loop_and_stream_final", side_effect=generate),
        patch("services.rag.save_usage"),
    ):
        frames = list(stream_rag_response("conversation", "Question", "owner", debug=False))
    answer = next(r for r in rows if r.get("role") == "assistant")
    if failed:
        assert "debug" not in answer
    else:
        timing = answer["debug"]["timings"]["total_seconds"]
        assert timing >= 0
        assert answer["debug"]["timing_only"]
        streamed = [json.loads(f[6:]) for f in frames if f.startswith("data: ")]
        assert any(f.get("debug") == answer["debug"] for f in streamed)
