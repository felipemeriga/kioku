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

IR_TOLERANCE = 0.02
RAGAS_TOLERANCE = 0.05

IR_METRICS = ("recall_at_5", "recall_at_10", "recall_at_20", "mrr", "ndcg_at_10")
RAGAS_METRICS = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


def main() -> int:
    if not LATEST_REPORT.exists():
        print(f"No report at {LATEST_REPORT}. Run `uv run python -m eval.runner` first.")
        return 1

    report = json.loads(LATEST_REPORT.read_text())
    agg = report["aggregate"]

    thresholds: dict[str, dict] = {}
    for m in IR_METRICS:
        v = agg.get("ir", {}).get(m)
        if v is None:
            continue
        thresholds[f"ir.{m}"] = {"min": round(v, 4), "tolerance": IR_TOLERANCE}

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
