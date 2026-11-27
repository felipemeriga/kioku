"""Compare bounded evidence reads and a second search page on sealed subsets."""

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from .lab import Lab
from .public_data import BASELINE, file_sha256, stable_priority, write_private
from .replay import code, payload
from .score_public import distribution, score_groups

DESIGNS = {
    "two_session_nearby": ("native_session_id", 1),
    "two_unique_excerpts": ("excerpt", 1),
    "two_session_wider": ("native_session_id", 3),
}


def freeze(directories, output):
    frozen = []
    for directory in directories:
        meta = json.loads((directory / "freeze.json").read_text())
        path = directory / "queries.json"
        if meta["baseline"] != BASELINE or file_sha256(path) != meta["sha256"]["queries.json"]:
            raise ValueError("A chapter changed after sealing")
        strata = defaultdict(list)
        for case in json.loads(path.read_text()):
            if case["stratum"] in {"abstention", "category_5"}:
                continue
            key = (
                (case["family"], case["stratum"])
                if case["family"] == "longmemeval_s"
                else (case["family"], case["cluster"])
            )
            strata[key].append(case)
        for (family, _), cases in sorted(strata.items()):
            target = 8 if family == "longmemeval_s" else 10
            frozen.extend(sorted(cases, key=lambda item: stable_priority(item["case_id"]))[:target])
    write_private(
        output,
        {
            "baseline": BASELINE,
            "cases": frozen,
            "limit": 10,
            "reads": 2,
            "design": DESIGNS,
            "char_limit": 4000,
            "source_query_hashes": [
                file_sha256(directory / "queries.json") for directory in directories
            ],
        },
    )
    return len(frozen)


def unique_contexts(matches, key, count):
    contexts = {}
    for match in matches:
        contexts.setdefault(match[key], match)
        if len(contexts) == count:
            break
    return contexts.values()


def retrieve(lab, case, plan):
    def summarize(result, ms, size, key):
        records = result.get(key, [])
        return {
            "status": code(result),
            "ids": [record["event_id"] for record in records],
            "bytes": size,
            "ms": ms,
            "truncated": sum(record.get("has_more") is True for record in records),
        }

    with lab.tools(case["owner"], case["root"]) as mcp:
        parameters = {
            "query": case["question"],
            **case["filters"],
            "order": "relevance",
            "limit": plan["limit"],
        }
        result, ms, size = payload(mcp.search_agent_history, **parameters)
        first = summarize(result, ms, size, "matches")
        options = []
        order = list(plan["design"])
        offset = int(stable_priority(case["case_id"]), 16) % len(order)
        for arm in order[offset:] + order[:offset]:
            key, radius = plan["design"][arm]
            arm_records = []
            for match in unique_contexts(result.get("matches", []), key, plan["reads"]):
                read, time_ms, bytes_read = payload(
                    mcp.read_agent_evidence,
                    reference=match["reference"],
                    before_records=radius,
                    after_records=radius,
                    char_limit=plan["char_limit"],
                )
                arm_records.append(summarize(read, time_ms, bytes_read, "evidence"))
            options.append({"arm": arm, "calls": arm_records})
        extra, ms, size = payload(mcp.search_agent_history, **parameters, offset=plan["limit"])
        options.append({"arm": "second_page", "calls": [summarize(extra, ms, size, "matches")]})
    return {
        "case_id": case["case_id"],
        "family": case["family"],
        "first": first,
        "arms": options,
    }


def score(plan, rows, frozen_dirs):
    gold = {}
    for directory in frozen_dirs:
        manifest = json.loads((directory / "freeze.json").read_text())
        path = directory / "gold.json"
        if manifest["sha256"]["gold.json"] != file_sha256(path):
            raise ValueError("Read-budget scoring labels differ from their sealed file")
        gold.update(json.loads(path.read_text()))
    metrics = defaultdict(Counter)
    latency = defaultdict(list)
    payloads = defaultdict(list)
    expected = {case["case_id"] for case in plan["cases"]}
    if len(rows) != len(expected) or {row["case_id"] for row in rows} != expected:
        raise ValueError("Read-budget outcomes must cover each sealed case once")
    for case in rows:
        labels = gold[case["case_id"]]["literal_turn_groups"]
        initial = case["first"]["ids"]
        before = score_groups(initial, labels, len(initial))
        for arm in case["arms"]:
            key = f"{case['family']}/{arm['arm']}"
            stats = metrics[key]
            stats["attempted"] += 1
            stats["first_search_errors"] += case["first"]["status"] != "ok"
            stats["follow_up_calls"] += len(arm["calls"])
            stats["follow_up_errors"] += sum(call["status"] != "ok" for call in arm["calls"])
            stats["truncated_records"] += sum(call["truncated"] for call in arm["calls"])
            latency[key].append(sum(call["ms"] for call in arm["calls"]))
            payloads[key].append(sum(call["bytes"] for call in arm["calls"]))
            if before is None:
                continue
            augmented = list(
                dict.fromkeys(
                    [
                        *initial,
                        *(record for call in arm["calls"] for record in call["ids"]),
                    ]
                )
            )
            after = score_groups(augmented, labels, len(augmented))
            stats["eligible_any"] += 1
            stats["first_any"] += before["any"]
            stats["augmented_any"] += after["any"]
            if before["all"] is not None:
                stats["eligible_all"] += 1
                stats["first_all"] += before["all"]
                stats["augmented_all"] += after["all"]
    return {
        "cases": len(rows),
        "groups": {key: dict(summary) for key, summary in sorted(metrics.items())},
        "follow_up_ms": {key: distribution(values) for key, values in sorted(latency.items())},
        "follow_up_bytes": {key: distribution(values) for key, values in sorted(payloads.items())},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, nargs="+")
    parser.add_argument("--lab", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.phase == "freeze":
        count = freeze(args.frozen, args.plan)
        print(f"Froze {count} read-budget control questions.")
        return
    plan = json.loads(args.plan.read_text())
    design = {key: tuple(value) for key, value in plan["design"].items()}
    if plan["baseline"] != BASELINE or design != DESIGNS:
        raise ValueError("The replay must use the original read-budget policy")
    if args.phase == "run":
        lab = Lab(args.lab)
        try:
            start = time.perf_counter()
            rows = [retrieve(lab, case, plan) for case in plan["cases"]]
            write_private(
                args.output,
                {
                    "plan_sha256": file_sha256(args.plan),
                    "rows": rows,
                    "elapsed_ms": (time.perf_counter() - start) * 1000,
                },
            )
            print(f"Replayed {len(rows)} read-budget controls.")
        finally:
            lab.close()
    else:
        raw = json.loads(args.replay.read_text())
        if raw["plan_sha256"] != file_sha256(args.plan):
            raise ValueError("The read-budget plan changed after the run")
        write_private(args.output, score(plan, raw["rows"], args.frozen))
        print(f"Scored {len(raw['rows'])} read-budget controls.")


if __name__ == "__main__":
    main()
