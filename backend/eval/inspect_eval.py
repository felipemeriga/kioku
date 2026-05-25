"""Read eval-results/latest.json and print the worst-scoring questions.

Usage:
    uv run python -m eval.inspect_eval                       # worst answer_relevancy (default)
    uv run python -m eval.inspect_eval --metric faithfulness # any RAGAS metric
    uv run python -m eval.inspect_eval --metric mrr          # any IR metric
    uv run python -m eval.inspect_eval --top 10              # show 10 instead of 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LATEST = Path(__file__).resolve().parent / "eval-results" / "latest.json"

RAGAS_METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
IR_METRICS = ("recall_at_5", "recall_at_10", "recall_at_20", "mrr", "ndcg_at_10")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metric", default="answer_relevancy")
    parser.add_argument("--top", type=int, default=5, help="how many worst questions to show")
    args = parser.parse_args()

    if not LATEST.exists():
        print(f"No report at {LATEST}. Run eval first.", file=sys.stderr)
        return 1

    report = json.loads(LATEST.read_text())
    rows = [q for q in report["per_question"] if q["mode"] == "full"]

    metric = args.metric
    is_ragas = metric in RAGAS_METRICS
    is_ir = metric in IR_METRICS
    if not (is_ragas or is_ir):
        print(f"Unknown metric: {metric}. Pick one of:", file=sys.stderr)
        print(f"  RAGAS: {RAGAS_METRICS}", file=sys.stderr)
        print(f"  IR:    {IR_METRICS}", file=sys.stderr)
        return 2

    def _score(q: dict) -> float:
        if is_ragas:
            return (q.get("ragas_scores") or {}).get(metric, 0.0) or 0.0
        return (q.get("scores") or {}).get(metric, 0.0) or 0.0

    rows.sort(key=_score)
    print(f"\nWorst {args.top} questions by {metric}:\n")
    for q in rows[: args.top]:
        score = _score(q)
        retrieved = q.get("retrieved_ids", [])
        expected = q.get("expected_ids", [])
        hit_count = len(set(retrieved) & set(expected))
        print(f"  [{q['id']}] {metric}={score:.3f}  ({q['difficulty']}/{q['retrieval_type']})")
        # Echo all RAGAS scores so we see if one specific question is broadly bad
        if q.get("ragas_scores"):
            short = "  ".join(f"{k}={v:.2f}" for k, v in q["ragas_scores"].items() if v is not None)
            print(f"     ragas: {short}")
        print(f"     retrieval: {hit_count}/{len(expected)} relevant chunks hit")
        # Look up the question text from golden_set context inside per_question
        # (we didn't store it explicitly — derive from id by reading golden_set)
        print(f"     Q: {_question_text(q['id'])}")
        if q.get("response"):
            resp = q["response"]
            preview = resp if len(resp) <= 350 else resp[:350].rstrip() + " ..."
            print(f"     A: {preview}")
        print()
    return 0


_QUESTIONS_BY_ID: dict[str, str] | None = None


def _question_text(qid: str) -> str:
    global _QUESTIONS_BY_ID
    if _QUESTIONS_BY_ID is None:
        import yaml

        gs = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "golden_set.yaml"
        _QUESTIONS_BY_ID = {q["id"]: q["question"] for q in yaml.safe_load(gs.read_text())}
    return _QUESTIONS_BY_ID.get(qid, "<unknown>")


if __name__ == "__main__":
    sys.exit(main())
