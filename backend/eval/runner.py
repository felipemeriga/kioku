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
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from eval.ir_metrics import mrr, ndcg_at_k, recall_at_k
from services.embeddings import embed_query
from services.ingestion import ingest_document
from services.metrics import collect_request
from services.search import search_documents

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
    embedding = embed_query(q["question"])
    t0 = time.monotonic()
    with collect_request(f"eval q={q['id']} mode={mode}"):
        results = search_documents(
            query_embedding=embedding,
            query_text=q["question"],
            user_id=EVAL_USER_ID,
            fast_mode=(mode == "fast"),
        )
    latency_ms = int((time.monotonic() - t0) * 1000)

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
    }


def _aggregate(per_question: list[dict]) -> dict:
    """Compute aggregate IR scores from per-question results."""
    out: dict[str, Any] = {"ir": {}, "by_mode": {}, "by_difficulty": {}}

    metric_keys = [f"recall_at_{k}" for k in K_VALUES] + ["mrr", "ndcg_at_10"]

    def _mean(values: list[float | None]) -> float | None:
        filtered = [v for v in values if v is not None]
        return round(sum(filtered) / len(filtered), 4) if filtered else None

    for metric in metric_keys:
        all_vals = [q["scores"][metric] for q in per_question]
        out["ir"][metric] = _mean(all_vals)

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
    """Return True if the report passes the baseline gate, False otherwise."""
    if not BASELINE_PATH.exists():
        print("[eval] no baseline.json yet — gate bypassed (first run).")
        return True

    baseline = json.loads(BASELINE_PATH.read_text())
    thresholds = baseline.get("thresholds", {})
    all_pass = True
    for key, spec in thresholds.items():
        section, metric = key.split(".", 1)
        if section != "ir":
            continue  # RAGAS is soft-gate, handled separately in Task 12
        actual = report["aggregate"]["ir"].get(metric)
        if actual is None:
            print(f"[eval]   {key}: missing in report — FAIL")
            all_pass = False
            continue
        floor = spec["min"] - spec["tolerance"]
        ok = actual >= floor
        sym = "PASS" if ok else "FAIL"
        print(
            f"[eval]   [{sym}] {key}: actual={actual:.4f} min={spec['min']:.4f} floor={floor:.4f}"
        )
        if not ok:
            all_pass = False
    return all_pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--gate", action="store_true", help="Fail with non-zero exit if baseline regression."
    )
    args = parser.parse_args()

    questions = yaml.safe_load(GOLDEN_SET.read_text())
    print(f"[eval] loaded {len(questions)} golden questions")

    _ingest_corpus()

    per_question = []
    for q in questions:
        for mode in ("full", "fast"):
            print(f"[eval] scoring q={q['id']} mode={mode}...")
            per_question.append(_score_question(q, mode))

    report = {
        "git_sha": _git_sha(),
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "aggregate": _aggregate(per_question),
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
