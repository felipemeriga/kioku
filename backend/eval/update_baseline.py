"""Write baseline.json from the current eval-results/latest.json.

Run after intentionally improving retrieval quality:
    uv run python -m eval.update_baseline
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

LATEST_REPORT = Path(__file__).resolve().parent / "eval-results" / "latest.json"
BASELINE = Path(__file__).resolve().parent / "baseline.json"

# Per-metric tolerances. Rank-sensitive metrics (mrr, ndcg) carry a wider band
# because the LLM-driven rewrite + multi-query stages introduce ~0.05 run-to-run
# variance on a 50-question eval, while recall is stable to ~0.03.
IR_TOLERANCES = {
    "recall_at_5": 0.02,
    "recall_at_10": 0.02,
    "recall_at_20": 0.02,
    "mrr": 0.05,
    "ndcg_at_10": 0.05,
}
RAGAS_TOLERANCE = 0.05

RAGAS_METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


def main() -> int:
    if not LATEST_REPORT.exists():
        print(f"No report at {LATEST_REPORT}. Run `uv run python -m eval.runner` first.")
        return 1

    report = json.loads(LATEST_REPORT.read_text())
    agg = report["aggregate"]

    thresholds: dict[str, dict] = {}
    for m, tol in IR_TOLERANCES.items():
        v = agg.get("ir", {}).get(m)
        if v is None:
            continue
        thresholds[f"ir.{m}"] = {"min": round(v, 4), "tolerance": tol}

    for m in RAGAS_METRICS:
        v = (agg.get("ragas") or {}).get(m)
        if v is None:
            continue
        thresholds[f"ragas.{m}"] = {"min": round(v, 4), "tolerance": RAGAS_TOLERANCE}

    baseline = {
        "captured_at": datetime.utcnow().date().isoformat(),
        "git_sha": report.get("git_sha", "unknown"),
        "thresholds": thresholds,
    }

    BASELINE.write_text(json.dumps(baseline, indent=2) + "\n")
    print(f"Wrote {BASELINE}:")
    print(json.dumps(baseline, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
