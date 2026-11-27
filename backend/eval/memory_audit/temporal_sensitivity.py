"""Compare the full LongMemEval-S corpus with a typed question-time cutoff."""

import argparse
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .candidate_diagnostic import query_manifest
from .full_long_score import open_phase
from .lab import Lab
from .public_data import (
    DATASETS,
    file_sha256,
    gold_event,
    longmem_rows,
    namespace,
    opaque,
    write_private,
)
from .replay import code, payload
from .score_public import distribution

FAMILY = "longmemeval_s"
DATE = "%Y/%m/%d (%a) %H:%M"


def dt(value):
    return datetime.strptime(value, DATE).replace(tzinfo=timezone.utc)


def check_source(source):
    if file_sha256(source) != DATASETS[FAMILY]["sha256"]:
        raise ValueError("The timestamp source changed after the primary audit")


def freeze(source, folders, output):
    check_source(source)
    queries = {case["case_id"]: case for case in query_manifest(folders)}
    selected = []
    for row in longmem_rows(source):
        question_time = dt(row["question_date"])
        after = sum(dt(when) > question_time for when in row["haystack_dates"])
        if after:
            identity = opaque(FAMILY, row["question_id"], "case")
            selected.append(
                {
                    **queries[identity],
                    "as_of": question_time.isoformat(),
                    "later_source_sessions": after,
                }
            )
    if len(selected) != 76 or sum(item["later_source_sessions"] for item in selected) != 1475:
        raise ValueError("Typed-cutoff sensitivity population differs from the source timestamps")
    write_private(output, selected)
    return len(selected)


def run(lab, selected):
    rows = []
    for case in selected:
        bound = datetime.fromisoformat(case["as_of"])
        with lab.tools(case["owner"], case["root"]) as mcp:
            first, search_ms, byte_count = payload(
                mcp.search_agent_history,
                query=case["question"],
                order="relevance",
                limit=50,
                as_of=case["as_of"],
                **case["filters"],
            )
            matches = first.get("matches", [])
            discovered = [
                dict(event=match["event_id"], recorded_at=match["recorded_at"]) for match in matches
            ]
            chosen = {}
            for match in matches:
                chosen.setdefault(match["native_session_id"], match)
                if len(chosen) == 2:
                    break
            read_ms = []
            reads = []
            expanded = []
            for match in chosen.values():
                value, elapsed, _ = payload(
                    mcp.read_agent_evidence,
                    reference=match["reference"],
                    before_records=1,
                    after_records=1,
                    char_limit=4000,
                )
                read_ms.append(elapsed)
                reads.append(code(value))
                expanded.extend(
                    {"event": record["event_id"], "recorded_at": record["recorded_at"]}
                    for record in value.get("evidence", [])
                )
            rows.append(
                {
                    "case_id": case["case_id"],
                    "status": code(first),
                    "ms": search_ms,
                    "bytes": byte_count,
                    "component_ms": search_ms + sum(read_ms),
                    "read_statuses": reads,
                    "first_ten": discovered[:10],
                    "expanded": expanded,
                    "reported_before": first.get("time_scope", {}).get("before_exclusive"),
                    "request_before": (bound + timedelta(microseconds=1)).isoformat(),
                    "post_cutoff_records": sum(
                        not row["recorded_at"] or datetime.fromisoformat(row["recorded_at"]) > bound
                        for row in discovered + expanded
                    ),
                }
            )
    return rows


def late_turns(source, ids):
    check_source(source)
    labels = {}
    for row in longmem_rows(source):
        name = row["question_id"]
        cid = opaque(FAMILY, name, "case")
        if cid not in ids:
            continue
        when = dt(row["question_date"])
        scope = namespace(FAMILY, name)
        events = set()
        for offset, (stamp, turns) in enumerate(
            zip(row["haystack_dates"], row["haystack_sessions"], strict=True)
        ):
            native = opaque(scope["cluster"], "session", offset)
            base = dt(stamp)
            for position, turn in enumerate(turns, start=1):
                if turn.get("has_answer") and base + timedelta(microseconds=position - 1) > when:
                    events.add(gold_event(scope, native, position))
        labels[cid] = events
    return labels


def score(source, selected, rows, initial, initial_raw, extension, extension_raw):
    ids = {row["case_id"] for row in selected}
    if {row["case_id"] for row in rows} != ids or len(rows) != len(ids):
        raise ValueError("Typed-cutoff outcomes do not account for all the sealed questions")
    first = open_phase(initial, initial_raw)
    second = open_phase(extension, extension_raw)
    full = {
        row["case_id"]: row for row in first["rows"] + second["rows"] if row["arm"] == "literal"
    }
    labels = {**first["labels"], **second["labels"]}
    excluded = late_turns(source, ids)
    counts = Counter()
    for row in rows:
        identity = row["case_id"]
        label = labels[identity]
        counts["errors"] += row["status"] != "ok"
        counts["read_errors"] += sum(status != "ok" for status in row["read_statuses"])
        counts["reported_bound_mismatch"] += row["reported_before"] != row["request_before"]
        counts["post_cutoff_records"] += row["post_cutoff_records"]
        if label["expect_abstain"]:
            counts["abstention_probes"] += 1
            continue
        counts["answerable"] += 1
        targets = {anchor for group in label["literal_turn_groups"] for anchor in group}
        usable = targets - excluded[identity]
        counts["with_later_marked_turns"] += targets != usable
        counts["no_marked_turn_before_cutoff"] += not usable
        if usable:
            counts["answerable_with_eligible_marked_turns"] += 1
            full_ids = [item["event"] for item in full[identity]["events"][:10]]
            bounded_ids = [item["event"] for item in row["first_ten"]]
            counts["same_eligible_gold_full_any_at_10"] += bool(usable.intersection(full_ids))
            counts["same_eligible_gold_cutoff_any_at_10"] += bool(usable.intersection(bounded_ids))
            counts["same_eligible_gold_full_all_at_10"] += usable.issubset(full_ids)
            counts["same_eligible_gold_cutoff_all_at_10"] += usable.issubset(bounded_ids)
    return {
        "cases": len(rows),
        "counter": dict(counts),
        "cutoff_search_ms": distribution(row["ms"] for row in rows),
        "cutoff_components_ms": distribution(row["component_ms"] for row in rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run", "score"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--initial", type=Path)
    parser.add_argument("--extension", type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--lab", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--initial-replay", type=Path)
    parser.add_argument("--extension-replay", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.phase == "freeze":
        count = freeze(args.data, [args.initial, args.extension], args.plan)
        print(f"Froze {count} affected LongMemEval-S timestamp cases.")
        return
    queries = json.loads(args.plan.read_text())
    if args.phase == "run":
        lab = Lab(args.lab)
        try:
            write_private(
                args.output, {"plan_sha256": file_sha256(args.plan), "rows": run(lab, queries)}
            )
            print(f"Replayed {len(queries)} typed cutoff controls.")
        finally:
            lab.close()
    else:
        raw = json.loads(args.replay.read_text())
        if raw["plan_sha256"] != file_sha256(args.plan):
            raise ValueError("Typed-cutoff queries changed after sealing")
        result = score(
            args.data,
            queries,
            raw["rows"],
            args.initial,
            args.initial_replay,
            args.extension,
            args.extension_replay,
        )
        write_private(args.output, result)


if __name__ == "__main__":
    main()
