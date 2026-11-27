import json
from types import SimpleNamespace
from unittest.mock import Mock

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


def test_score_question_fetches_enough_hits_to_measure_each_cutoff(runner, monkeypatch):
    embedding = [0.1]
    results = [{"content_hash": "file", "metadata": {"chunk_index": index}} for index in range(20)]
    from services.ai.scope import current_scope

    def scoped_search(**kwargs):
        assert current_scope().owner_id == runner.EVAL_USER_ID
        assert current_scope().folder_ids == (runner.EVAL_FOLDER_ID,)
        return results

    search = Mock(side_effect=scoped_search)
    monkeypatch.setenv("RAG_METRICS", "1")
    monkeypatch.setattr(runner, "embed_query", lambda query: embedding)
    monkeypatch.setattr(runner, "search_documents", search)
    question = {
        "id": "q001",
        "question": "where is the answer?",
        "difficulty": "hard",
        "retrieval_type": "factual",
        "relevant_chunk_ids": ["sha256:file:chunk_19"],
    }

    scores = runner._score_question(question, "fast")["scores"]

    assert search.call_args.kwargs["top_k"] == 20
    assert search.call_args.kwargs["folder_ids"] == [runner.EVAL_FOLDER_ID]
    assert scores["recall_at_5"] == scores["recall_at_10"] == 0
    assert scores["recall_at_20"] == 1
    assert scores["mrr"] == 1 / 20
    assert scores["ndcg_at_10"] == 0


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


@pytest.mark.parametrize(
    ("problem", "error"),
    [
        ("missing-question", "question coverage"),
        ("duplicate-question", "question coverage"),
        ("no-context", "q2: missing answer or retrieved context"),
        ("no-response", "q2: missing answer or retrieved context"),
        ("short-result", "RAGAS returned 1 rows for 2 questions"),
        ("nan", "q2: missing or nonfinite faithfulness"),
        ("missing-field", "q2: missing or nonfinite context_recall"),
        (None, None),
    ],
)
def test_ragas_requires_all_answers_contexts_and_metrics(runner, monkeypatch, problem, error):
    import ragas

    questions = [
        {"id": q, "question": q, "ground_truth_answer": f"answer to {q}"} for q in ("q1", "q2")
    ]
    full = [{"id": q["id"], "mode": "full"} for q in questions]
    if problem == "missing-question":
        full.pop()
    if problem == "duplicate-question":
        full[1] = full[0]

    def answer(question, user_id, scope_folder_ids):
        assert user_id == runner.EVAL_USER_ID
        assert scope_folder_ids == [runner.EVAL_FOLDER_ID]
        return {
            "response": "" if question == "q2" and problem == "no-response" else question,
            "retrieved_chunks": [] if question == "q2" and problem == "no-context" else ["source"],
        }

    rows = [dict.fromkeys(runner.RAGAS_METRICS, float(i)) for i in (0, 1)]
    if problem == "short-result":
        rows.pop()
    if problem == "nan":
        rows[1]["faithfulness"] = float("nan")
    if problem == "missing-field":
        del rows[1]["context_recall"]
    evaluate = Mock(return_value=SimpleNamespace(scores=rows))
    monkeypatch.setattr(runner, "answer_question", answer)
    monkeypatch.setattr(runner, "_get_ragas_llm", Mock())
    monkeypatch.setattr(runner, "VoyageEmbeddings", Mock())
    monkeypatch.setattr(ragas, "evaluate", evaluate)

    if error:
        with pytest.raises(runner.RagasCoverageError, match=error):
            runner._run_ragas(full, questions)
    else:
        result = runner._run_ragas(full, questions)
        assert list(result["per_question"]) == ["q1", "q2"]
        assert result["aggregate"] == dict.fromkeys(runner.RAGAS_METRICS, 0.5)
    if problem in {"missing-question", "duplicate-question", "no-context", "no-response"}:
        evaluate.assert_not_called()


def test_ragas_failure_writes_an_invalid_report(runner, monkeypatch, tmp_path):
    golden = tmp_path / "golden.yaml"
    golden.write_text("- id: q001\n")
    monkeypatch.setattr(runner, "GOLDEN_SET", golden)
    monkeypatch.setattr(runner, "EVAL_RESULTS_DIR", tmp_path)
    monkeypatch.setattr(runner, "_ingest_corpus", lambda: None)
    monkeypatch.setattr(runner.sys, "argv", ["eval.runner", "--ragas"])

    def score(question, mode):
        return {
            "id": question["id"],
            "mode": mode,
            "difficulty": "easy",
            "scores": dict.fromkeys(runner.IR_METRICS, 1.0),
            "latency_ms": 1,
        }

    monkeypatch.setattr(runner, "_score_question", score)
    monkeypatch.setattr(
        runner, "_run_ragas", Mock(side_effect=runner.RagasCoverageError("q001: missing context"))
    )
    assert runner.main() == 1
    report = json.loads((tmp_path / "latest.json").read_text())
    assert report["jobs_completed"] == 2
    assert report["ragas"] == {"expected": 1, "completed": 0, "error": "q001: missing context"}
    assert "ragas" not in report["aggregate"]
