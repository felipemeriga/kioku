"""End-to-end eval runner: ingest fixtures, retrieve per golden question, score.

Run locally:
    cd backend
    supabase start
    psql postgresql://postgres:postgres@127.0.0.1:54322/postgres -f db/schema.sql
    RAG_METRICS=1 uv run python -m eval.runner

Run with the CI gate (compares aggregates to baseline.json):
    uv run python -m eval.runner --gate
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Load .env (for VOYAGE_API_KEY / ANTHROPIC_API_KEY) BEFORE importing modules
# that read env at import time. Callers override SUPABASE_URL/SUPABASE_SERVICE_KEY
# on the command line to point at the local stack instead of prod.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _guard_against_prod() -> None:
    """Refuse to run if SUPABASE_URL points at a remote (prod-looking) host.

    The eval harness ingests fixture documents and runs queries against
    a throwaway database. Hitting prod by accident would pollute it with
    test data under EVAL_USER_ID.
    """
    url = os.environ.get("SUPABASE_URL", "")
    if not url:
        sys.exit("[eval] SUPABASE_URL is not set. Export local stack URL before running.")
    if "127.0.0.1" in url or "localhost" in url:
        return
    if os.environ.get("EVAL_ALLOW_REMOTE") == "1":
        print(f"[eval] WARNING: SUPABASE_URL={url!r} looks remote; EVAL_ALLOW_REMOTE=1 honored.")
        return
    sys.exit(
        f"[eval] refusing to run against non-local SUPABASE_URL={url!r}. "
        "Set SUPABASE_URL=http://127.0.0.1:54321 (and matching SUPABASE_SERVICE_KEY) "
        "or export EVAL_ALLOW_REMOTE=1 to override."
    )


_guard_against_prod()

from eval.ir_metrics import mrr, ndcg_at_k, recall_at_k  # noqa: E402
from services.embeddings import embed_query  # noqa: E402
from services.evaluation import VoyageEmbeddings, _get_ragas_llm  # noqa: E402
from services.ingestion import ingest_document  # noqa: E402
from services.metrics import collect_request  # noqa: E402
from services.rag import answer_question  # noqa: E402
from services.search import search_documents  # noqa: E402

EVAL_USER_ID = "00000000-0000-0000-0000-000000000001"
FIXTURE_CORPUS = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "corpus"
GOLDEN_SET = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden_set.yaml"
EVAL_RESULTS_DIR = Path(__file__).resolve().parent / "eval-results"
BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"

K_VALUES = (5, 10, 20)


def _ingest_corpus() -> None:
    """Ingest every file in the fixture corpus under EVAL_USER_ID."""
    files = sorted(p for p in FIXTURE_CORPUS.iterdir() if p.is_file())
    print(f"[eval] ingesting {len(files)} fixture files...")
    for path in files:
        raw = path.read_bytes()
        result = ingest_document(
            file_bytes=raw,
            filename=path.name,
            user_id=EVAL_USER_ID,
            folder_id=None,
        )
        print(f"[eval]   {path.name}: chunks={result['chunks']} duplicate={result['duplicate']}")


def _chunk_id_of(doc: dict) -> str:
    """Reconstruct the canonical chunk_id used in golden_set labels."""
    meta = doc.get("metadata") or {}
    return f"sha256:{doc.get('content_hash')}:chunk_{meta.get('chunk_index')}"


def _score_question(q: dict, mode: str) -> dict:
    """Run retrieval for one golden question and return per-question scores."""
    # Force the metrics collector on for eval — we capture proxy_metrics in the
    # report regardless of the user's shell env. setdefault would silently
    # leave it disabled if RAG_METRICS=0 was already exported.
    os.environ["RAG_METRICS"] = "1"

    embedding = embed_query(q["question"])
    t0 = time.monotonic()
    with collect_request(f"eval q={q['id']} mode={mode}") as collector:
        results = search_documents(
            query_embedding=embedding,
            query_text=q["question"],
            user_id=EVAL_USER_ID,
            fast_mode=(mode == "fast"),
        )
    latency_ms = int((time.monotonic() - t0) * 1000)

    proxy: dict[str, float] = {}
    if collector is not None:
        for stage, kvs in collector._stages:
            for k, v in kvs.items():
                if isinstance(v, (int, float)) and v is not None:
                    proxy[f"{stage}.{k}"] = float(v)

    retrieved_ids = [_chunk_id_of(r) for r in results]
    relevant_ids = set(q["relevant_chunk_ids"])

    scores: dict[str, float | None] = {}
    for k in K_VALUES:
        scores[f"recall_at_{k}"] = recall_at_k(retrieved_ids, relevant_ids, k)
    scores["mrr"] = mrr(retrieved_ids, relevant_ids)
    scores["ndcg_at_10"] = ndcg_at_k(retrieved_ids, relevant_ids, 10)

    return {
        "id": q["id"],
        "mode": mode,
        "difficulty": q["difficulty"],
        "retrieval_type": q["retrieval_type"],
        "scores": scores,
        "retrieved_ids": retrieved_ids,
        "expected_ids": list(relevant_ids),
        "latency_ms": latency_ms,
        "proxy_metrics": proxy,
    }


def _aggregate(per_question: list[dict]) -> dict:
    """Compute aggregate IR scores from per-question results."""
    out: dict[str, Any] = {
        "ir": {},
        "by_mode": {},
        "by_difficulty": {},
        "proxy_metrics_means": {},
    }

    metric_keys = [f"recall_at_{k}" for k in K_VALUES] + ["mrr", "ndcg_at_10"]

    def _mean(values: list[float | None]) -> float | None:
        filtered = [v for v in values if v is not None]
        return round(sum(filtered) / len(filtered), 4) if filtered else None

    for metric in metric_keys:
        all_vals = [q["scores"][metric] for q in per_question]
        out["ir"][metric] = _mean(all_vals)

    # Aggregate proxy metrics across all questions
    proxy_keys = sorted({pk for q in per_question for pk in q.get("proxy_metrics", {})})
    for pk in proxy_keys:
        vals = [q["proxy_metrics"].get(pk) for q in per_question]
        out["proxy_metrics_means"][pk] = _mean(vals)

    for mode in ("fast", "full"):
        mode_qs = [q for q in per_question if q["mode"] == mode]
        if mode_qs:
            out["by_mode"][mode] = {
                metric: _mean([q["scores"][metric] for q in mode_qs]) for metric in metric_keys
            }
            out["by_mode"][mode + "_latency_p50_ms"] = int(
                _percentile([q["latency_ms"] for q in mode_qs], 50)
            )
        else:
            out["by_mode"][mode] = None

    for diff in ("easy", "medium", "hard"):
        diff_qs = [q for q in per_question if q["difficulty"] == diff]
        if diff_qs:
            out["by_difficulty"][diff] = {
                metric: _mean([q["scores"][metric] for q in diff_qs]) for metric in metric_keys
            }

    return out


def _percentile(values: list[float], p: int) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * (p / 100)
    f = int(k)
    if f == len(s) - 1:
        return s[f]
    return s[f] + (s[f + 1] - s[f]) * (k - f)


def _git_sha() -> str:
    import subprocess

    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"]).decode().strip()
    except Exception:
        return "unknown"


def _write_report(report: dict) -> Path:
    EVAL_RESULTS_DIR.mkdir(exist_ok=True)
    timestamped = EVAL_RESULTS_DIR / f"{int(time.time())}.json"
    latest = EVAL_RESULTS_DIR / "latest.json"
    text = json.dumps(report, indent=2)
    timestamped.write_text(text)
    latest.write_text(text)
    return timestamped


def _check_gate(report: dict) -> bool:
    """Return True if the report passes the baseline gate.

    Hard-gates on IR metrics; warns on RAGAS deltas without failing.
    """
    if not BASELINE_PATH.exists():
        print("[eval] no baseline.json yet — gate bypassed (first run).")
        return True

    baseline = json.loads(BASELINE_PATH.read_text())
    thresholds = baseline.get("thresholds", {})
    all_pass = True
    for key, spec in thresholds.items():
        section, metric = key.split(".", 1)
        actual_section = report["aggregate"].get(section) or {}
        actual = actual_section.get(metric)
        if actual is None:
            print(f"[eval]   {key}: missing in report — FAIL")
            if section == "ir":
                all_pass = False
            continue
        floor = spec["min"] - spec["tolerance"]
        ok = actual >= floor
        if section == "ir":
            sym = "PASS" if ok else "FAIL"
        else:
            sym = "OK" if ok else "WARN"
        soft_tag = " (soft)" if section == "ragas" else ""
        print(
            f"[eval]   [{sym}] {key}{soft_tag}: actual={actual:.4f} "
            f"min={spec['min']:.4f} floor={floor:.4f}"
        )
        if not ok and section == "ir":
            all_pass = False
    return all_pass


def _run_ragas(per_question: list[dict], questions: list[dict]) -> dict:
    """Run RAGAS on questions that have at least one retrieved context.

    Re-runs retrieval per question to capture the actual content text (we only
    kept IDs in per_question). Marginal extra cost is fine for eval.
    """
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.metrics import (
        AnswerRelevancy,
        ContextPrecision,
        ContextRecall,
        Faithfulness,
    )

    # Pick the "full" mode results for RAGAS — fast mode is the same retrieval
    # path minus query expansion; scoring both doubles cost without much signal.
    full_results = {q["id"]: q for q in per_question if q["mode"] == "full"}
    q_by_id = {q["id"]: q for q in questions}

    samples = []
    sample_qids: list[str] = []
    sample_responses: dict[str, str] = {}
    for qid in full_results:
        q = q_by_id[qid]
        result = answer_question(q["question"], EVAL_USER_ID)
        contexts = result["retrieved_chunks"]
        response = result["response"]
        if not contexts:
            continue
        sample = SingleTurnSample(
            user_input=q["question"],
            response=response,
            retrieved_contexts=contexts,
            reference=q["ground_truth_answer"],
        )
        samples.append(sample)
        sample_qids.append(qid)
        sample_responses[qid] = response

    if not samples:
        return {"aggregate": {}, "per_question": {}}

    dataset = EvaluationDataset(samples=samples)
    metrics = [Faithfulness(), AnswerRelevancy(), ContextPrecision(), ContextRecall()]

    def _run_evaluate():
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return evaluate(
                dataset=dataset,
                metrics=metrics,
                llm=_get_ragas_llm(),
                embeddings=VoyageEmbeddings(),
            )
        finally:
            loop.close()

    result = _run_evaluate()

    def _sanitize(v):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    aggregate = {k: _sanitize(v) for k, v in result._repr_dict.items()}

    # Per-question scores — aligned with samples by index. Lets diagnostic
    # tooling show "this exact question scored low, here's the answer it gave".
    per_question: dict[str, dict] = {}
    df = result.to_pandas()
    metric_cols = [
        c
        for c in df.columns
        if c
        in (
            "faithfulness",
            "answer_relevancy",
            "context_precision",
            "context_recall",
        )
    ]
    for idx, qid in enumerate(sample_qids):
        if idx >= len(df):
            break
        per_question[qid] = {
            "response": sample_responses[qid],
            "scores": {col: _sanitize(df.iloc[idx][col]) for col in metric_cols},
        }

    return {"aggregate": aggregate, "per_question": per_question}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gate", action="store_true", help="Fail with non-zero exit if baseline regression."
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help=(
            "Run only questions tagged `quick: true` in golden_set.yaml "
            "(curated 1-per-cell subset for fast prompt-iteration loops). "
            "RAGAS is noisier with the smaller N — use for trend, not for gating."
        ),
    )
    args = parser.parse_args()

    questions = yaml.safe_load(GOLDEN_SET.read_text())
    if args.quick:
        questions = [q for q in questions if q.get("quick")]
        print(f"[eval] --quick: loaded {len(questions)} of golden set")
    else:
        print(f"[eval] loaded {len(questions)} golden questions")

    _ingest_corpus()

    per_question = []
    for q in questions:
        for mode in ("full", "fast"):
            print(f"[eval] scoring q={q['id']} mode={mode}...")
            per_question.append(_score_question(q, mode))

    aggregate = _aggregate(per_question)
    print("[eval] running RAGAS...")
    ragas_result = _run_ragas(per_question, questions)
    aggregate["ragas"] = ragas_result.get("aggregate", {})

    # Merge per-question RAGAS data (response + per-q scores) into per_question
    # entries with mode='full' so diagnostic tooling can show "this answer for
    # qNNN scored AR=0.X".
    ragas_per_q = ragas_result.get("per_question", {})
    for entry in per_question:
        if entry["mode"] != "full":
            continue
        merged = ragas_per_q.get(entry["id"])
        if not merged:
            continue
        entry["response"] = merged["response"]
        entry["ragas_scores"] = merged["scores"]

    report = {
        "git_sha": _git_sha(),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "aggregate": aggregate,
        "per_question": per_question,
    }

    path = _write_report(report)
    print(f"[eval] wrote {path}")
    print(json.dumps(report["aggregate"], indent=2))

    if args.gate:
        ok = _check_gate(report)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
