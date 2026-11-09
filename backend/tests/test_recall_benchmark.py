"""Measurement contracts: no duplicate inference identity or misleading quality/timing wins."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest


def load_script(name):
    path = Path(__file__).parents[2] / "scripts" / "benchmarks" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


report = load_script("recall_report")
runner = load_script("recall_effort")


def test_parallel_tool_intervals_are_counted_once():
    tools = [
        {"started_at": "2026-01-01T00:00:00Z", "finished_at": "2026-01-01T00:00:10Z"},
        {"started_at": "2026-01-01T00:00:05Z", "finished_at": "2026-01-01T00:00:20Z"},
        {"name": "bootstrap_without_observed_times"},
    ]
    assert report.tool_union(tools) == 20


def test_retrieving_a_gold_anchor_does_not_make_an_unsupported_answer_correct():
    state = {
        "key": "00-positive-low",
        "pair": 0,
        "effort": "low",
        "success": True,
        "verified_control": {"effort": "low"},
        "terminal": {"replace": "Unsupported claim [9]", "citations": [{"number": 1}]},
        "artifacts": [
            {
                "tool": {"name": "search_agent_history", "input": {"query": "alpha"}},
                "chunks": [{"result": json.dumps({"matches": [{"event_id": "gold"}]})}],
            }
        ],
    }
    row = report.metrics(
        state,
        {"id": "positive", "question": "Recall alpha"},
        {"positive": ["gold"]},
        {"00-positive-low": {"verdict": "fail", "score": 0, "note": "unsupported"}},
    )
    assert row["direct_anchor_hit"]
    assert not row["citation_numbers_resolve"]
    summary = report.aggregate([row])["low"]
    assert summary["manual_mean_score"] == 0
    assert "runner_seconds" not in summary["timings"]


def test_execution_failures_remain_in_denominator_without_fabricated_zero_latency():
    state = {
        "key": "00-positive-high",
        "pair": 0,
        "effort": "high",
        "success": False,
        "terminal": {"error": "wall_timeout"},
    }
    row = report.metrics(
        state, {"id": "positive", "question": "Recall alpha"}, {"positive": ["gold"]}, {}
    )
    summary = report.aggregate([row])["high"]
    assert summary["trials"] == 1 and summary["completed"] == 0
    assert summary["expanded_anchor_hits"] == 0 and summary["anchor_cases"] == 1
    assert "runner_seconds" not in summary["timings"]


def test_interrupted_benchmark_replays_same_turn_and_never_replaces_failed_trial(tmp_path):
    class Client:
        def __init__(self):
            self.creates = 0
            self.bodies = []

        def credentials(self):
            return {"user_id": "owner"}

        def request(self, method, path, **kwargs):
            if method == "POST":
                self.creates += 1
                return SimpleNamespace(json=lambda: {"id": "owned-conversation"})
            return SimpleNamespace(json=lambda: {"messages": []})

        def stream_chat(self, body):
            self.bodies.append(body)
            if len(self.bodies) == 1:
                raise httpx.ReadError("Connection lost after admission")
            return [
                {
                    "done": True,
                    "message_id": "answer",
                    "replace": "alpha",
                    "debug": {"execution": {"usage": {"thinking_control": {"effort": "low"}}}},
                }
            ], {}

    item = {"key": "00-positive-low", "pair": 0, "question_index": 0, "effort": "low"}
    client = Client()
    with pytest.raises(RuntimeError, match="same turn"):
        runner.trial(client, tmp_path, item, "Recall alpha", "folder", "haiku")
    result = runner.trial(client, tmp_path, item, "Recall alpha", "folder", "haiku")
    assert result["finished"] and result["success"]
    assert client.creates == 1 and client.bodies[0] == client.bodies[1]
    assert client.bodies[1]["reasoning_effort"] == "low"
    runner.trial(client, tmp_path, item, "Recall alpha", "folder", "haiku")
    assert len(client.bodies) == 2
    with pytest.raises(ValueError, match="scope or question"):
        # An unfinished request is immutable even if a caller changes scope.
        result.pop("finished")
        runner.save(tmp_path / (item["key"] + ".json"), result)
        runner.trial(client, tmp_path, item, "Recall alpha", "different-folder", "haiku")


@pytest.mark.parametrize(
    "owner,title,state,expected",
    [
        (None, "expected", "committed", 1),
        ("foreign", "expected", "committed", 0),
        (None, "user renamed it", "committed", 0),
        (None, "expected", "submitted", 0),
    ],
)
def test_cleanup_only_removes_owned_terminal_exported_unchanged_fixtures(
    tmp_path, owner, title, state, expected
):
    item = {"key": "00-positive-low"}
    expected_title = "effort-bench-" + tmp_path.name + "-" + item["key"]
    row = {"key": item["key"], "finished": True, "conversation_id": "owned", "turn_id": "turn"}
    runner.save(tmp_path / (item["key"] + ".json"), row)

    class Client:
        def __init__(self):
            self.deleted = []

        def credentials(self):
            return {"user_id": "owner"}

        def request(self, method, path, **kwargs):
            if method == "DELETE":
                self.deleted.append(path)
                return None
            if "/turns/" in path:
                return SimpleNamespace(json=lambda: {"state": state})
            saved = {"id": "owned", "title": expected_title if title == "expected" else title}
            if owner is not None:
                saved["user_id"] = owner
            return SimpleNamespace(json=lambda: saved)

    client = Client()
    assert runner.cleanup(client, tmp_path, [item])["deleted"] == expected
    assert len(client.deleted) == expected


def test_failed_native_attempt_time_is_included_when_recovered():
    state = {
        "key": "00-positive-high",
        "pair": 0,
        "effort": "high",
        "success": False,
        "terminal": {"error": {"code": "wall_timeout"}},
        "failure_telemetry": {"attempts": [{"elapsed_seconds": 308.7, "usage": None}]},
    }
    row = report.metrics(state, {"id": "positive", "question": "Recall alpha"}, {}, {})
    summary = report.aggregate([row])["high"]
    assert summary["completed"] == 0
    assert summary["timings"]["runner_seconds"]["p95"] == 308.7
    assert row["thinking_tokens"] is None
    assert row["error_code"] == "wall_timeout"
