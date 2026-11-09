"""Do not manufacture a speedup by changing concurrency or selecting successes."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/benchmarks"))
from compare_chat_latency import compare  # noqa: E402


@pytest.fixture
def pair(tmp_path):
    roots = [tmp_path / name for name in ("before", "after")]
    for index, root in enumerate(roots):
        root.mkdir()
        meta = {
            "manifest_sha256": "frozen",
            "workers": 2,
            "api_base": "https://production.test",
            "path": "production",
        }
        (root / "run.json").write_text(json.dumps(meta))
        (root / "summary.json").write_text('{"planned_turns":1}')
        case = {
            "id": "real-question",
            "case": {"content": "Exact prompt", "model": "haiku"},
            "context": "fresh",
            "success": True,
            "publication_verified": True,
            "first_visible_text_seconds": 40 - index * 20,
            "complete_seconds": 60 - index * 25,
            "started_at": "2026-11-09T20:00:00+00:00",
            "debug": {
                "execution": {
                    "usage": {"model_usage": {"haiku-version": {}}},
                    "timings": {"attempts": [{"queue_wait_seconds": 1, "elapsed_seconds": 45}]},
                },
                "tool_calls": [{"origin": "backend_bootstrap"}],
            },
        }
        (root / "case-000-000.json").write_text(json.dumps(case))
    return roots


def mutate(path, field, value):
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))


def test_matched_comparison_keeps_queue_and_bootstrap_distinct(pair):
    report = compare(*pair)
    row = report["rows"][0]
    assert row["complete_seconds_saved"] == 25
    assert row["before"]["native_tool_calls"] == 0
    assert row["before"]["bootstrap_calls"] == 1
    assert row["before"]["queue_seconds"] == 1


@pytest.mark.parametrize("field,value", [("workers", 1), ("manifest_sha256", "changed")])
def test_rejects_unmatched_workload(pair, field, value):
    mutate(pair[1] / "run.json", field, value)
    with pytest.raises(ValueError, match="Unmatched"):
        compare(*pair)


def test_missing_failed_or_different_context_cannot_be_filtered_away(pair):
    mutate(pair[1] / "summary.json", "planned_turns", 2)
    with pytest.raises(ValueError, match="Missing planned"):
        compare(*pair)
    mutate(pair[1] / "summary.json", "planned_turns", 1)
    mutate(pair[1] / "case-000-000.json", "publication_verified", False)
    with pytest.raises(ValueError, match="Unverified publication"):
        compare(*pair)


def test_resolved_alias_model_drift_is_rejected(pair):
    mutate(
        pair[1] / "case-000-000.json",
        "debug",
        {"execution": {"usage": {"model_usage": {"different-haiku-version": {}}}}},
    )
    with pytest.raises(ValueError, match="Resolved model drift"):
        compare(*pair)
