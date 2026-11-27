"""Check equal page size, ranking repeatability, scope caps, and timestamp routing."""

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

from services import evidence_prefetch
from services.agent_memory_tools import execute_memory_tool

from .lab import Lab
from .operational import AuditClock
from .operational_fixtures import ZONE
from .public_data import BASELINE, file_sha256, json_text, stable_priority, uuid_for, write_private
from .replay import code
from .score_public import distribution, ranked_units

TIMESTAMP_CASES = (
    "As of 2026-11-21 at exactly 01:00:00 in America/New_York, "
    "what did we observe for EXACT_CUTOFF?",
    "As of 2026-11-21T01:00:00.000000-05:00, what did we observe for EXACT_CUTOFF?",
    "As of 2026-11-21, what did we observe for EXACT_CUTOFF?",
)


def result_ids(result):
    return [item["event_id"] for item in result.get("matches", [])]


def timed_search(mcp, lab, case, limit, offset=0):
    started = time.perf_counter()
    rpc_start = lab.db_wall["rpc"]
    result = json.loads(
        mcp.search_agent_history(
            case["question"], order="relevance", limit=limit, offset=offset, **case["filters"]
        )
    )
    return {
        "ms": (time.perf_counter() - started) * 1000,
        "rpc_ms": (lab.db_wall["rpc"] - rpc_start) * 1000,
        "status": result["status"],
        "code": code(result),
        "events": result_ids(result),
        "next_offset": result.get("next_offset"),
        "has_more": result.get("has_more"),
    }


def compare(lab, plan, original):
    old = {
        row["case_id"]: row
        for row in original
        if row["record_type"] == "trial" and row["arm"] == "literal"
    }
    summaries = []
    measurements = defaultdict(list)
    for case in plan["query_cases"]:
        with lab.tools(case["owner"], case["root"]) as mcp:
            for budget in (10, 50):
                timed_search(mcp, lab, case, budget)  # unscored warm-up
            rows = {10: [], 50: []}
            for i in range(plan["repetitions"]):
                for budget in (10, 50) if i % 2 == 0 else (50, 10):
                    sample = timed_search(mcp, lab, case, budget)
                    rows[budget].append(sample)
                    measurements[budget].append(sample["ms"])
            second = timed_search(mcp, lab, case, 10, offset=10)
        ten, fifty = [row[0]["events"] for row in (rows[10], rows[50])]
        past = ranked_units(old[case["case_id"]], "literal_turn")[:10]
        summaries.append(
            {
                "case_id": case["case_id"],
                "status": [sample["code"] for samples in rows.values() for sample in samples],
                "first_page_same_order": ten == fifty[:10],
                "first_page_same_membership": set(ten) == set(fifty[:10]),
                "first_page_same_as_initial50_order": fifty[:10] == past,
                "first_page_same_as_initial50_membership": set(fifty[:10]) == set(past),
                "second_page_same_membership": set(second["events"]) == set(fifty[10:20]),
                "paged_duplicate_ids": len(set(ten) & set(second["events"])),
                "warm_ranking_counts": {
                    budget: len({tuple(sample["events"]) for sample in samples})
                    for budget, samples in rows.items()
                },
                "timings_ms": {
                    budget: distribution(sample["ms"] for sample in samples)
                    for budget, samples in rows.items()
                },
            }
        )
    return {
        "case_count": len(summaries),
        "cases": summaries,
        "warm_sample_ms": {size: distribution(times) for size, times in measurements.items()},
    }


def timestamp_controls(lab, plan, operations):
    owner = operations["owners"]["owner"]
    folder = operations["folders"]["cedar-client"]
    cutoff = "2026-11-21T01:00:00.000000-05:00"
    outputs = []
    with lab.tools(owner, folder), patch.object(evidence_prefetch, "datetime", AuditClock):

        def execute(name, arguments):
            if name == "knowledge_base_search":
                return json_text({"status": "unavailable", "code": "knowledge_not_seeded"})
            return execute_memory_tool(lab, name, arguments, owner, [folder])

        explicit = json.loads(
            execute(
                "search_agent_history",
                {
                    "query": "EXACT_CUTOFF",
                    "as_of": cutoff,
                    "timezone": ZONE,
                },
            )
        )
        for variant, question in enumerate(plan["timestamp_cases"]):
            _, calls = evidence_prefetch.prefetch(question, ZONE, execute)
            first = calls[0]
            discovered = json.loads(first["result"])
            read = [
                item["event_id"]
                for call in calls
                if call["name"] == "read_agent_evidence"
                for item in json.loads(call["result"]).get("evidence", [])
            ]
            outputs.append(
                {
                    "variant": variant,
                    "route": first["name"],
                    "scope": discovered.get("time_scope"),
                    "retrieved": result_ids(discovered),
                    "expanded": read,
                }
            )
        _, calls = evidence_prefetch.prefetch(plan["historical_overview_case"], ZONE, execute)
        historical = json.loads(calls[0]["result"])
        overview_control = {
            "routed_to": calls[0]["name"],
            "projection": calls[0]["input"].get("projection"),
            "as_of": calls[0]["input"].get("as_of"),
            "status": code(historical),
        }
    return {
        "explicit_as_of_scope": explicit.get("time_scope"),
        "explicit_as_of_retrieved": result_ids(explicit),
        "prefetch": outputs,
        "historical_overview": overview_control,
    }


def scope_control(lab, output):
    owner = uuid_for(output.name, "scope-owner")
    root = uuid_for(output.name, "scope-root")
    lab.create_owner(owner)
    lab.create_folder(root, owner, "scope-cap")
    for i in range(99):
        lab.create_folder(uuid_for(root, i), owner, f"scope-child-{i}", root)
    with lab.tools(owner, root) as mcp:
        one_hundred = json.loads(mcp.search_agent_history("nonexistent"))
    lab.create_folder(uuid_for(root, 99), owner, "scope-child-99", root)
    with lab.tools(owner, root) as mcp:
        too_broad = json.loads(mcp.search_agent_history("nonexistent"))
        named = json.loads(mcp.search_agent_history("nonexistent", folder="scope-child-0"))
    with lab.tools(owner, uuid_for(root, 0)) as mcp:
        separate_repo_key = json.loads(mcp.search_agent_history("nonexistent"))
    return {
        "100_root_and_repos": code(one_hundred),
        "101_root_and_repos": code(too_broad),
        "101_with_named_repo_filter": code(named),
        "repo_scoped_key": code(separate_repo_key),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run"))
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--lab", type=Path)
    parser.add_argument("--initial", type=Path, required=True)
    parser.add_argument("--initial-replay", type=Path)
    parser.add_argument("--operations", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.phase == "freeze":
        query_path = args.initial / "queries.json"
        metadata = json.loads((args.initial / "freeze.json").read_text())
        if file_sha256(query_path) != metadata["sha256"]["queries.json"]:
            raise ValueError("Initial queries changed")
        groups = defaultdict(list)
        for case in json.loads(query_path.read_text()):
            if case["family"] == "longmemeval_s":
                groups[case["stratum"]].append(case)
        selected = [
            case
            for cases in groups.values()
            for case in sorted(cases, key=lambda item: stable_priority(item["case_id"]))[:2]
        ]
        write_private(
            args.frozen,
            {
                "baseline": BASELINE,
                "timestamp_cases": TIMESTAMP_CASES,
                "historical_overview_case": "As of 2026-11-20, what did we work on?",
                "query_cases": selected,
                "repetitions": 5,
                "initial_query_sha256": file_sha256(query_path),
            },
        )
        print(f"Froze {len(selected)} replay sentinels and three timestamp-routing probes.")
        return
    plan = json.loads(args.frozen.read_text())
    if plan["baseline"] != BASELINE or plan["initial_query_sha256"] != file_sha256(
        args.initial / "queries.json"
    ):
        raise ValueError("Sentinel plan changed its release or source population")
    from .score_public import json_lines

    lab = Lab(args.lab)
    try:
        rank = compare(lab, plan, json_lines(args.initial_replay))
        wording = timestamp_controls(
            lab, plan, json.loads((args.operations / "sources.json").read_text())
        )
        scopes = scope_control(lab, args.output)
        counters = Counter(status for case in rank["cases"] for status in case["status"])
        write_private(
            args.output,
            {
                "baseline": BASELINE,
                "plan_sha256": file_sha256(args.frozen),
                "rank": rank,
                "timestamp_routing": wording,
                "scope_caps": scopes,
                "sentinel_status_counts": dict(counters),
            },
        )
        print(f"Replayed {rank['case_count']} rank sentinels and all scope/time controls.")
    finally:
        lab.close()


if __name__ == "__main__":
    main()
