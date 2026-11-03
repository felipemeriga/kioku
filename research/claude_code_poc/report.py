"""Aggregate safe metrics. Never sums cumulative native session costs per turn."""

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path


def percentile(values, quantile):
    return (
        round(sorted(values)[max(0, math.ceil(len(values) * quantile) - 1)], 3)
        if values
        else None
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--runtime", type=Path, default=Path("/private/tmp/kioku-claude-poc-runtime")
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    calls = []
    for path in args.runtime.rglob("calls.jsonl"):
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row["experiment"] = str(path.parent.relative_to(args.runtime))
            calls.append(row)
    sessions = defaultdict(Decimal)
    for call in calls:
        sid = call.get("session_id")
        if sid and call.get("list_cost_usd") is not None:
            sessions[sid] = max(sessions[sid], Decimal(str(call["list_cost_usd"])))
    groups = defaultdict(list)
    for call in calls:
        groups[call["experiment"]].append(call)
    experiments = {}
    for key, rows in groups.items():
        successes = [
            r
            for r in rows
            if r["returncode"] == 0
            and not r.get("is_error")
            and "result" in r.get("event_types", [])
        ]
        latencies = [r["elapsed_s"] for r in successes]
        ttfts = [
            r["first_text_s"] for r in successes if r.get("first_text_s") is not None
        ]
        experiments[key] = {
            "calls": len(rows),
            "successes": len(successes),
            "forced_cancellations": sum(bool(r.get("forced_cancel")) for r in rows),
            "returncodes": dict(Counter(str(r["returncode"]) for r in rows)),
            "p50_latency_s": round(statistics.median(latencies), 3)
            if latencies
            else None,
            "p95_latency_s": percentile(latencies, 0.95),
            "p50_first_text_s": round(statistics.median(ttfts), 3) if ttfts else None,
            "resolved_models": sorted(
                {model for r in rows for model in (r.get("model_usage") or {})}
            ),
        }
    duplex = {}
    for path in args.runtime.rglob("duplex-checkpoint.json"):
        state = json.loads(path.read_text())
        turns = state["turns"]
        for turn in turns:
            if turn.get("list_cost_usd") is not None:
                sid = turn.get("session_id") or state["session_id"]
                sessions[sid] = max(sessions[sid], Decimal(str(turn["list_cost_usd"])))
        duplex[str(path.parent.relative_to(args.runtime))] = {
            "start_utc": state["start_utc"],
            "status": state["status"],
            "elapsed_s": state.get("elapsed_s"),
            "turns": len(turns),
            "recall_correct": sum(bool(t.get("recall_correct")) for t in turns),
            "errors": [t for t in turns if t.get("error")],
            "process_ids": sorted({t["pid"] for t in turns if t.get("pid")}),
            "p50_latency_s": percentile(
                [t["elapsed_s"] for t in turns if t.get("elapsed_s")], 0.5
            ),
        }
    soak = json.loads((args.runtime / "soak/checkpoint.json").read_text())
    report = {
        "scope": "local native subscription POC, not production integration",
        "monetary_subscription_charge": "not exposed by CLI; no monetary savings claim",
        "list_cost_equivalent_lower_bound_usd": str(sum(sessions.values(), Decimal(0))),
        "cost_accounting_note": "max cumulative total per session, never sum per-turn totals; cancelled calls can have unreported usage; simultaneous same-session totals may race",
        "calls": len(calls),
        "experiments": experiments,
        "duplex": duplex,
        "soak": {
            "started_utc": soak["started_utc"],
            "status": soak["status"],
            "elapsed_s": soak.get("elapsed_s"),
            "cycles": len(soak["cycles"]),
            "failed_checks": [
                {
                    "cycle": cycle["index"],
                    "checks": cycle["checks"],
                    "error": cycle.get("error"),
                }
                for cycle in soak["cycles"]
                if cycle.get("error") or not all(cycle["checks"].values())
            ],
            "supervisor_restarts": soak.get("supervisor_restarts", []),
        },
    }
    resource_path = args.runtime / "resources.jsonl"
    if resource_path.exists():
        samples = [json.loads(line) for line in resource_path.read_text().splitlines()]
        report["resources"] = {
            "samples": len(samples),
            "peak_sum_process_rss_mib": round(
                max(x["sum_process_rss_kib"] for x in samples) / 1024, 1
            ),
            "note": "Sum of descendant process RSS, not unique physical memory",
        }
    output = args.output or args.runtime / "summary.json"
    output.write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {
                "calls": len(calls),
                "soak_elapsed_s": soak.get("elapsed_s"),
                "cost_lower_bound_usd": report["list_cost_equivalent_lower_bound_usd"],
                "output": str(output),
            }
        )
    )


if __name__ == "__main__":
    main()
