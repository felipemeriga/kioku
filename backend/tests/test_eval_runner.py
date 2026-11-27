import json

import pytest

from eval.ir_metrics import ndcg_at_k


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "http://127.0.0.1:54321")
    from eval import runner

    return runner


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost.example.invalid",
        "https://example.invalid/127.0.0.1",
        "https://example.invalid/?next=localhost",
    ],
)
def test_eval_guard_rejects_remote_host_with_loopback_substring(runner, monkeypatch, url):
    monkeypatch.setenv("SUPABASE_URL", url)
    monkeypatch.delenv("EVAL_ALLOW_REMOTE", raising=False)
    with pytest.raises(SystemExit):
        runner._guard_against_prod()


def test_ndcg_credits_a_repeated_hit_once_without_compressing_ranks():
    assert ndcg_at_k(["a", "a"], {"a"}, 2) == 1.0
    assert ndcg_at_k(["a", "a", "b"], {"a", "b"}, 3) == ndcg_at_k(
        ["a", "irrelevant", "b"], {"a", "b"}, 3
    )


def test_gate_requires_both_modes_to_meet_the_floor(runner, monkeypatch, tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "thresholds": {
                    f"ir.{metric}": {"min": 0.9, "tolerance": 0.0} for metric in runner.IR_METRICS
                }
            }
        )
    )
    monkeypatch.setattr(runner, "BASELINE_PATH", baseline)
    high = dict.fromkeys(runner.IR_METRICS, 1.0)
    low = dict.fromkeys(runner.IR_METRICS, 0.8)
    report = {"aggregate": {"ir": high, "by_mode": {"fast": high, "full": low}}}
    assert not runner._check_gate(report)
    report["aggregate"]["by_mode"]["full"] = high
    assert runner._check_gate(report)
    baseline.write_text('{"thresholds": {}}')
    assert not runner._check_gate(report)


def test_incomplete_eval_writes_failed_question_and_exits_unsuccessfully(
    runner, monkeypatch, tmp_path
):
    golden = tmp_path / "golden.yaml"
    golden.write_text("- id: q001\n")
    monkeypatch.setattr(runner, "GOLDEN_SET", golden)
    monkeypatch.setattr(runner, "EVAL_RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "_ingest_corpus", lambda: None)
    monkeypatch.setattr(runner.sys, "argv", ["eval.runner"])

    def score(question, mode):
        if mode == "full":
            raise RuntimeError("provider error")
        return {
            "id": question["id"],
            "mode": mode,
            "difficulty": "easy",
            "scores": dict.fromkeys(runner.IR_METRICS, 1.0),
            "latency_ms": 1,
        }

    monkeypatch.setattr(runner, "_score_question", score)
    assert runner.main() == 1
    report = json.loads((tmp_path / "latest.json").read_text())
    assert report["jobs_expected"] == 2
    assert report["jobs_completed"] == 1
    assert report["failures"] == [{"id": "q001", "mode": "full", "error": "RuntimeError"}]
