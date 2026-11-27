"""Locate LongMemEval misses within the frozen PostgreSQL candidate stages."""

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from psycopg import sql

from .full_long_score import open_phase
from .lab import Lab
from .mechanism import candidate_parameters, candidate_prefix
from .public_data import BASELINE, file_sha256, write_private
from .replay import log_line, open_output
from .score_public import distribution, json_lines


def query_manifest(folders):
    result = []
    for folder in folders:
        path = folder / "queries.json"
        bundle = json.loads((folder / "freeze.json").read_text())
        if bundle["baseline"] != BASELINE or file_sha256(path) != bundle["sha256"]["queries.json"]:
            raise ValueError("This diagnostic requires the original frozen questions")
        result.extend(
            case for case in json.loads(path.read_text()) if case["family"] == "longmemeval_s"
        )
    if len(result) != 500 or len({case["case_id"] for case in result}) != len(result):
        raise ValueError("This diagnostic expects the full unique LongMemEval-S population")
    if any(case["filters"] != {"timezone": "UTC"} for case in result):
        raise ValueError("Use the original complete-haystack projection")
    return result


def replay(lab, queries, output):
    query = candidate_prefix(lab) + sql.SQL("""
      SELECT (SELECT COALESCE(array_agg(DISTINCT event_id),'{}') FROM matched) AS pre_focus,
             (SELECT COALESCE(array_agg(DISTINCT event_id),'{}') FROM focused) AS post_focus
    """)
    with open_output(output) as stream:
        for case in queries:
            arguments = candidate_parameters(case["owner"], case["folder"], case["question"])
            started = time.perf_counter()
            records = lab.pg.execute(query, arguments).fetchone()
            log_line(
                stream,
                {
                    "case_id": case["case_id"],
                    "stratum": case["stratum"],
                    "elapsed_ms": (time.perf_counter() - started) * 1000,
                    **records,
                },
            )


def score_candidate_stages(
    candidate_path, first_frozen, first_raw, extension_frozen, extension_raw
):
    first = open_phase(first_frozen, first_raw)
    extension = open_phase(extension_frozen, extension_raw)
    gold = {**first["labels"], **extension["labels"]}
    original = {
        row["case_id"]: row for row in first["rows"] + extension["rows"] if row["arm"] == "literal"
    }
    seen = set()
    strata = defaultdict(Counter)
    partial = defaultdict(Counter)
    timings = []
    for row in json_lines(candidate_path):
        identity = row["case_id"]
        if identity in seen or identity not in original or identity not in gold:
            raise ValueError("Candidate replay identity does not match the original data")
        seen.add(identity)
        trial = original[identity]
        if trial["stratum"] != row["stratum"]:
            raise ValueError("Candidate replay query type changed")
        if trial["status"] != "ok" or not trial["availability"]:
            raise ValueError("Separate availability failures before scoring candidate stages")
        labels = gold[identity]
        if labels["expect_abstain"]:
            continue
        targets = {anchor for group in labels["literal_turn_groups"] for anchor in group}
        if not targets:
            continue
        before = set(row["pre_focus"])
        after = set(row["post_focus"])
        direct = [event["event"] for event in trial["events"]]
        if not after.issubset(before) or not set(direct).issubset(after):
            raise ValueError("Candidate pipeline disagrees with the original retrieval")
        timings.append(row["elapsed_ms"])
        if targets.intersection(direct[:10]):
            state = "returned_first_10"
        elif targets.intersection(direct):
            state = "returned_after_10"
        elif targets.intersection(after):
            state = "focused_candidate_beyond_first_50"
        elif targets.intersection(before):
            state = "removed_by_identifier_focus"
        else:
            state = "absent_from_lexical_candidates"
        for key in ("all", row["stratum"]):
            strata[key][state] += 1
            partial[key]["marked_turns"] += len(targets)
            partial[key]["before_focus"] += len(targets & before)
            partial[key]["after_focus"] += len(targets & after)
            partial[key]["first_10"] += len(targets & set(direct[:10]))
    if seen != set(original):
        raise ValueError("Candidate replay omitted some frozen queries")
    return {
        "cases": len(seen),
        "replay_sha256": file_sha256(candidate_path),
        "per_question_first_anchor_stage": {key: dict(count) for key, count in strata.items()},
        "marked_turn_counts": {key: dict(count) for key, count in partial.items()},
        "sql_read_only_wall_ms": distribution(timings),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("replay", "score"))
    parser.add_argument("--initial", type=Path, required=True)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--lab", type=Path)
    parser.add_argument("--initial-replay", type=Path)
    parser.add_argument("--extension-replay", type=Path)
    parser.add_argument("--candidate-file", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    if args.phase == "replay":
        lab = Lab(args.lab)
        try:
            replay(lab, query_manifest([args.initial, args.extension]), args.candidate_file)
            print("Compared matched and focused candidate sets for all 500 questions.")
        finally:
            lab.close()
    else:
        result = score_candidate_stages(
            args.candidate_file,
            args.initial,
            args.initial_replay,
            args.extension,
            args.extension_replay,
        )
        write_private(args.summary, result)
        print(f"Classified candidate stages for {result['cases']} recorded questions.")


if __name__ == "__main__":
    main()
