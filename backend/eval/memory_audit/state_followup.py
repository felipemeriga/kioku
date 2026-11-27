"""Replay final-action evidence using the session found by ordinary STATE search."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .lab import Lab
from .public_data import file_sha256, stable_priority, write_private
from .replay import archive_fixture, code, corpus_groups, payload, verify_frozen
from .score_public import distribution

FAMILIES = ("state_train_replay", "state_train_full")


def followup(lab, frozen, family):
    manifest = verify_frozen(frozen, family)
    queries = json.loads((frozen / "queries.json").read_text())
    inventory = []
    expected_records = {}
    if family == "state_train_full":
        groups = {case["cluster"] for case in queries}
        for _, histories in corpus_groups(frozen / f"{family}.jsonl", groups):
            expected, state = archive_fixture(lab, histories[0]["scope"], histories)
            if not state["available"]:
                raise RuntimeError("STATE follow-up requires all trajectories searchable")
            expected_records.update(expected)
            inventory.append(state)
            print(f"Archived and indexed {state['sessions_expected']} trajectories.", flush=True)
        queries.sort(key=lambda row: stable_priority(row["case_id"]))
    rows = []
    for case in queries:
        with lab.tools(case["owner"], case["root"]) as mcp:
            first, first_ms, first_bytes = payload(
                mcp.search_agent_history,
                query=case["question"],
                order="relevance",
                limit=10,
                **case["filters"],
            )
            initial = first.get("matches") or []
            row = {
                "case_id": case["case_id"],
                "first_status": code(first),
                "first_ids": [record["event_id"] for record in initial],
                "session": None,
                "latest_ids": [],
                "read_ids": [],
                "ms": first_ms,
                "bytes": first_bytes,
                "calls": 1,
            }
            if initial:
                native = initial[0]["native_session_id"]
                latest, latest_ms, latest_bytes = payload(
                    mcp.search_agent_history,
                    query="",
                    order="latest",
                    session=native,
                    limit=10,
                    **case["filters"],
                )
                matches = latest.get("matches") or []
                row.update(
                    {
                        "session": native,
                        "latest_status": code(latest),
                        "latest_ids": [record["event_id"] for record in matches],
                        "ms": first_ms + latest_ms,
                        "bytes": first_bytes + latest_bytes,
                        "calls": 2,
                    }
                )
                result = next(
                    (record for record in matches if record["event_type"] == "tool_result"), None
                )
                if result:
                    expanded, read_ms, read_bytes = payload(
                        mcp.read_agent_evidence,
                        reference=result["reference"],
                        before_records=0,
                        after_records=0,
                        char_limit=4000,
                    )
                    row.update(
                        {
                            "read_status": code(expanded),
                            "read_ids": [
                                record["event_id"] for record in expanded.get("evidence", [])
                            ],
                            "ms": row["ms"] + read_ms,
                            "bytes": row["bytes"] + read_bytes,
                            "calls": 3,
                        }
                    )
                    if expected_records:
                        row["read_integrity_errors"] = sum(
                            record["event_id"] not in expected_records
                            or not expected_records[record["event_id"]].validates(record)
                            for record in expanded.get("evidence", [])
                        )
            rows.append(row)
    return {
        "gold_sha256": manifest["sha256"]["gold.json"],
        "query_sha256": manifest["sha256"]["queries.json"],
        "inventory": inventory,
        "rows": rows,
    }


def metrics_for(rows, gold):
    metrics = {
        "cases": len(rows),
        "located_correct_session_at_1": sum(
            [row["session"]] in gold[row["case_id"]]["session_groups"] for row in rows
        ),
        "both_in_latest_since_selected_session": sum(
            all(
                set(group) & set(row["latest_ids"])
                for group in gold[row["case_id"]]["literal_turn_groups"]
            )
            for row in rows
        ),
        "both_in_paired_read": sum(
            not row.get("read_integrity_errors")
            and all(
                set(group) & set(row["read_ids"])
                for group in gold[row["case_id"]]["literal_turn_groups"]
            )
            for row in rows
        ),
        "component_ms": distribution(row["ms"] for row in rows),
        "component_bytes": distribution(row["bytes"] for row in rows),
        "calls": sum(row["calls"] for row in rows),
        "search_errors": sum(row["first_status"] != "ok" for row in rows),
        "latest_errors": sum(row.get("latest_status", "ok") != "ok" for row in rows),
        "read_errors": sum(row.get("read_status", "ok") != "ok" for row in rows),
        "read_integrity_errors": sum(row.get("read_integrity_errors", 0) for row in rows),
    }
    if all("first_ids" in row for row in rows):
        coverage = [
            [
                bool(set(group) & set(row["first_ids"]))
                for group in gold[row["case_id"]]["literal_turn_groups"]
            ]
            for row in rows
        ]
        metrics["any_in_first_ten"] = sum(map(any, coverage))
        metrics["both_in_first_ten"] = sum(map(all, coverage))
    return metrics


def score(frozen, raw):
    manifest = json.loads((frozen / "freeze.json").read_text())
    path = frozen / "gold.json"
    sealed_gold = manifest["sha256"][path.name]
    if raw["gold_sha256"] != sealed_gold or file_sha256(path) != sealed_gold:
        raise ValueError("STATE labels changed after freezing")
    gold = json.loads(path.read_text())
    row_ids = {row["case_id"] for row in raw["rows"]}
    if row_ids != set(gold) or len(row_ids) != len(raw["rows"]):
        raise ValueError("STATE follow-up does not cover every frozen question exactly once")
    query = frozen / "queries.json"
    if (
        manifest["sha256"][query.name] != file_sha256(query)
        or raw.get("query_sha256", manifest["sha256"][query.name]) != manifest["sha256"][query.name]
    ):
        raise ValueError("STATE queries changed after freezing")
    groups = defaultdict(list)
    domains = {case["case_id"]: case["stratum"] for case in json.loads(query.read_text())}
    actually_shortened = defaultdict(list)
    for row in raw["rows"]:
        case_label = gold[row["case_id"]]
        if "formulation" not in case_label:
            continue
        treatment = case_label["formulation"]
        domain = domains[row["case_id"]]
        groups[treatment].append(row)
        groups[f"{treatment}/{domain}"].append(row)
        if case_label["actually_shortened"]:
            actually_shortened[treatment].append(row)
    result = metrics_for(raw["rows"], gold)
    if groups:
        result["groups"] = {group: metrics_for(rows, gold) for group, rows in groups.items()}
        result["actually_shortened"] = {
            group: metrics_for(rows, gold) for group, rows in actually_shortened.items()
        }
        result["inventory"] = raw["inventory"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("run", "score"))
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--family", choices=FAMILIES, default=FAMILIES[0])
    parser.add_argument("--lab", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    if options.phase == "run":
        lab = Lab(options.lab)
        try:
            write_private(options.output, followup(lab, options.frozen, options.family))
            print("Replayed STATE training final-action follow-up.")
        finally:
            lab.close()
    else:
        raw = json.loads(options.replay.read_text())
        write_private(options.output, score(options.frozen, raw))


if __name__ == "__main__":
    main()
