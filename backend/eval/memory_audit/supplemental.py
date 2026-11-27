"""Prepare released BEAM and MemoryAgentBench inputs for distinct retrieval probes."""

import argparse
import ast
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .lab import MIGRATION_DIRECTORY
from .public_data import (
    ARMS,
    BASELINE,
    READ_COUNT,
    READ_WINDOW,
    RELATED,
    SEED,
    codex_record,
    file_sha256,
    gold_event,
    namespace,
    opaque,
    session_row,
    stable_priority,
    write_private,
)
from .replay import log_line, open_output
from .score_public import distribution, json_lines, ranked_units

EXTRA_DATASETS = {
    "beam_100k": {
        "file": "beam-100k.parquet",
        "revision": "3205395e897e7318c7b094ef4e6047b9b82dbb03",
        "sha256": "c0519be25907005ba873c927c50877471d550873039d96c041554d0075a78ace",
        "projection": "20 complete chats, both roles, original nested sessions and date anchors.",
    },
    "mab_conflict": {
        "file": "mab-conflict.parquet",
        "revision": "7ea066982b140a19337e17e60d45d4076e042faf",
        "sha256": "24d5c3f09ce0ce15625cb9f8a98f44f0d864ca6c94d7b4ad04eb697ca3a5ff45",
        "projection": "Four full FactConsolidation contexts in source order, 64 lines per session.",
    },
}


def case(family, scope, source_id, stratum, question, split, *, revision=None):
    return {
        **scope,
        "case_id": opaque(family, source_id, "case"),
        "question": question,
        "family": family,
        "stratum": stratum,
        "split": split,
        "filters": {"timezone": "UTC"},
        "dataset_revision": revision or EXTRA_DATASETS[family]["revision"],
    }


def parse_beam(rows, session_sink, add_case):
    family = "beam_100k"
    for row in rows:
        source_id = row["conversation_id"]
        scope = namespace(family, source_id)
        anchors = {}
        for ordinal, session in enumerate(row["chat"]):
            native = opaque(scope["cluster"], "session", ordinal)
            base = datetime.strptime(session[0]["time_anchor"], "%B-%d-%Y").replace(
                tzinfo=timezone.utc
            )
            records = []
            for i, turn in enumerate(session, start=1):
                timestamp = base + timedelta(microseconds=i - 1)
                records.append(codex_record(turn["role"], turn["content"], timestamp))
                if turn["id"] in anchors:
                    raise ValueError("BEAM turn identity must be unique within its conversation")
                anchors[turn["id"]] = (native, gold_event(scope, native, i))
            log_line(session_sink, session_row(scope, native, records))
        # The authors stored Python literals in this Parquet field. literal_eval
        # decodes only data structures and never executes strings from the file.
        for category, probes in sorted(ast.literal_eval(row["probing_questions"]).items()):
            items = [(f"{source_id}:{category}:{i}", probe) for i, probe in enumerate(probes)]
            for rank, (qid, probe) in enumerate(
                sorted(items, key=lambda item: stable_priority(item[0]))
            ):
                source_ids = probe.get("source_chat_ids") or []
                clauses = source_ids if isinstance(source_ids, dict) else {}
                groups = (
                    list(clauses.values())
                    if clauses
                    else [item if isinstance(item, list) else [item] for item in source_ids]
                )
                targets = list(dict.fromkeys(eid for ids in groups for eid in ids))
                turns = [[anchors[eid][1]] if eid in anchors else [] for eid in targets]
                distinct_sessions = dict.fromkeys(
                    anchors[eid][0] for eid in targets if eid in anchors
                )
                answer = probe.get("ideal_answer", probe.get("ideal_response"))
                add_case(
                    case(
                        family,
                        scope,
                        qid,
                        category,
                        probe["question"],
                        "primary" if rank == 0 else "holdout",
                    ),
                    {
                        "source_id": qid,
                        "answer": answer,
                        "expect_abstain": category == "abstention",
                        "literal_turn_groups": turns,
                        "session_groups": [[sid] for sid in distinct_sessions],
                        "event_groups": [
                            [anchors[eid][1] for eid in group if eid in anchors] for group in groups
                        ],
                        "clause_names": list(clauses),
                    },
                )


def parse_mab(rows, session_sink, add_case):
    family = "mab_conflict"
    contexts = {}
    for row in rows:
        source = row["metadata"]["source"]
        mode, size = source.rsplit("_", 2)[-2:]
        scope = namespace(family, size)
        if size not in contexts:
            contexts[size] = row["context"]
            statements = row["context"].splitlines()
            when = datetime(2020, 1, 1, tzinfo=timezone.utc)
            for start in range(0, len(statements), 64):
                native = opaque(scope["cluster"], "segment", start)
                records = [
                    codex_record("user", text, when + timedelta(microseconds=index))
                    for index, text in enumerate(statements[start : start + 64], start=start)
                ]
                log_line(session_sink, session_row(scope, native, records))
        elif contexts[size] != row["context"]:
            raise ValueError("Single/multihop rows must carry the same source before sharing scope")
        parts = zip(row["metadata"]["qa_pair_ids"], row["questions"], row["answers"], strict=True)
        for source_id, question, values in parts:
            key = f"{size}:{mode}:{source_id}"
            add_case(
                case(
                    family,
                    scope,
                    key,
                    f"{size}_{mode}",
                    question,
                    "primary" if size in {"6k", "32k"} else "holdout",
                ),
                {"answer_values": values},
            )


def freeze_family(family, spec, data_dir, output, load):
    source = data_dir / spec["file"]
    if file_sha256(source) != spec["sha256"]:
        raise ValueError("The source differs from its published frozen file")
    if output.resolve().is_relative_to(MIGRATION_DIRECTORY.parents[1]):
        raise ValueError("Raw audit data must stay outside the worktree")
    output.mkdir(mode=0o700)
    cases = []
    gold = {}

    def add_case(query, labels):
        cases.append(query)
        gold[query["case_id"]] = labels

    with open_output(output / f"{family}.jsonl") as stream:
        load(source, stream, add_case)
    write_private(output / "queries.json", cases)
    write_private(output / "gold.json", gold)
    manifest = {
        "baseline": BASELINE,
        "seed": SEED,
        "datasets": {family: spec},
        "policy": {
            "arms": ARMS,
            "related": RELATED,
            "read_window": READ_WINDOW,
            "reads": READ_COUNT,
        },
        "cases": len(cases),
        "sha256": {path.name: file_sha256(path) for path in sorted(output.iterdir())},
    }
    write_private(output / "freeze.json", manifest)
    return manifest


def freeze_extra(family, data_dir, output):
    from pyarrow import parquet

    parse = parse_beam if family == "beam_100k" else parse_mab

    def load(path, stream, add_case):
        parse(parquet.read_table(path).to_pylist(), stream, add_case)

    return freeze_family(family, EXTRA_DATASETS[family], data_dir, output, load)


def mab_score(replay_path, frozen):
    manifest = json.loads((frozen / "freeze.json").read_text())
    checked = ("mab_conflict.jsonl", "gold.json")
    for name in checked:
        if file_sha256(frozen / name) != manifest["sha256"][name]:
            raise ValueError("The frozen scoring corpus changed")
    gold = json.loads((frozen / "gold.json").read_text())
    source = defaultdict(dict)
    for session in json_lines(frozen / "mab_conflict.jsonl"):
        scope = session["scope"]
        for position, record in enumerate(session["records"], start=1):
            source[scope["cluster"]][gold_event(scope, session["native"], position)] = record[
                "payload"
            ]["content"].casefold()
    results = defaultdict(Counter)
    latency = defaultdict(list)
    presence = {}
    expected = None
    completed = None
    for trial in json_lines(replay_path):
        if trial["record_type"] == "run":
            if trial["gold_hash"] != manifest["sha256"]["gold.json"]:
                raise ValueError("This run used different answers")
            expected = trial["expected_cases"]
        if trial["record_type"] == "completion":
            completed = trial["cases"]
        if trial["record_type"] != "trial":
            continue
        case_id = trial["case_id"]
        group_key = f"{trial['stratum']}/{trial['arm']}"
        stats = results[group_key]
        stats["attempted"] += 1
        stats["errors"] += trial["status"] != "ok"
        stats["availability_incomplete"] += not trial["availability"]
        latency[group_key].append(trial["search_ms"])
        accepted = [str(value).casefold().strip() for value in gold[case_id]["answer_values"]]
        accepted = [value for value in accepted if value]
        if not accepted:
            stats["missing_answer_values"] += 1
            continue
        lookup = source[trial["cluster"]]
        if case_id not in presence:
            presence[case_id] = any(value in line for line in lookup.values() for value in accepted)
        items = ranked_units(trial, "literal_turn")[:10]
        stats["answer_string_present_in_full_source"] += presence[case_id]
        stats["answer_string_in_first_10_records"] += any(
            value in lookup[event] for event in items if event in lookup for value in accepted
        )
    return {
        "dataset": "mab_conflict",
        "expected_cases": expected,
        "completed_cases": completed,
        "method": "Case-insensitive answer substring in full source records; no answer generation.",
        "groups": {key: dict(counts) for key, counts in sorted(results.items())},
        "search_ms": {key: distribution(values) for key, values in sorted(latency.items())},
        "raw_replay_sha256": file_sha256(replay_path),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--family", choices=sorted(EXTRA_DATASETS), required=True)
    freeze.add_argument("--data", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    mab = sub.add_parser("score-mab")
    mab.add_argument("--replay", type=Path, required=True)
    mab.add_argument("--frozen", type=Path, required=True)
    mab.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        manifest = freeze_extra(args.family, args.data, args.output)
        print(f"Froze {manifest['cases']} {args.family} cases.")
    else:
        result = mab_score(args.replay, args.frozen)
        write_private(args.output, result)
        print(f"Scored {result['completed_cases']} cases for substring availability.")


if __name__ == "__main__":
    main()
