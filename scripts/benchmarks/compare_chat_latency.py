"""Compare matched production runs; reject workload or publication mismatches."""

import argparse
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def cases(root):
    rows = [read(path) for path in sorted(Path(root).glob("case-*.json"))]
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate result IDs")
    return {row["id"]: row for row in rows}


def metrics(row):
    debug = row.get("debug") or {}
    execution = debug.get("execution") or {}
    attempts = (execution.get("timings") or {}).get("attempts") or []
    tools = debug.get("tool_calls") or []
    return {
        "first_text_seconds": row.get("first_visible_text_seconds"),
        "complete_seconds": row.get("complete_seconds"),
        "headers_seconds": row.get("headers_seconds"),
        "queue_seconds": sum(
            attempt.get("queue_wait_seconds") or 0 for attempt in attempts
        ),
        "attempt_seconds": sum(
            attempt.get("elapsed_seconds") or 0 for attempt in attempts
        ),
        "native_tool_calls": sum(
            tool.get("origin") != "backend_bootstrap" for tool in tools
        ),
        "bootstrap_calls": sum(
            tool.get("origin") == "backend_bootstrap" for tool in tools
        ),
        "resolved_models": sorted(
            ((execution.get("usage") or {}).get("model_usage") or {}).keys()
        ),
    }


def compare(before_root, after_root):
    before_meta, after_meta = (
        read(Path(before_root) / "run.json"),
        read(Path(after_root) / "run.json"),
    )
    for key in ("manifest_sha256", "workers", "api_base", "path"):
        if before_meta.get(key) != after_meta.get(key) or before_meta.get(key) is None:
            raise ValueError(f"Unmatched production run {key}")
    before, after = cases(before_root), cases(after_root)
    planned_before = read(Path(before_root) / "summary.json")["planned_turns"]
    planned_after = read(Path(after_root) / "summary.json")["planned_turns"]
    if (
        not before
        or before.keys() != after.keys()
        or len(before) != planned_before
        or len(after) != planned_after
    ):
        raise ValueError("Missing planned results; cannot compare incomplete cohorts")
    report = []
    for identifier, left in before.items():
        right = after[identifier]
        if left["case"] != right["case"] or left["context"] != right["context"]:
            raise ValueError(
                f"Unmatched prompt, scope, model, effort, or context: {identifier}"
            )
        if not all(
            row.get("success") and row.get("publication_verified")
            for row in (left, right)
        ):
            raise ValueError(f"Unverified publication: {identifier}")
        lhs, rhs = metrics(left), metrics(right)
        if (
            not lhs["resolved_models"]
            or lhs["resolved_models"] != rhs["resolved_models"]
        ):
            raise ValueError(f"Resolved model drift: {identifier}")
        report.append(
            {
                "id": identifier,
                "before": lhs,
                "after": rhs,
                "complete_seconds_saved": lhs["complete_seconds"]
                - rhs["complete_seconds"],
                "first_text_seconds_saved": lhs["first_text_seconds"]
                - rhs["first_text_seconds"],
                "local_date_changed": left["started_at"][:10]
                != right["started_at"][:10],
            }
        )
    return {
        "matched": True,
        "workers": before_meta["workers"],
        "rows": report,
        "quality": "Not graded here; transport/publication success is not answer accuracy",
        "clock": "Client monotonic delivery times; native queue and attempts shown separately",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    args = parser.parse_args()
    print(json.dumps(compare(args.before, args.after), indent=2))


if __name__ == "__main__":
    main()
