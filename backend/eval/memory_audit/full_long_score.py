"""Combine the disjoint LongMemEval-S score phases without pooling latency."""

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .public_data import file_sha256, write_private
from .score_public import GOLD_FIELDS, abstention_controls, metric, paired, read_replay, score_arm


def open_phase(frozen, raw):
    freeze = frozen / "freeze.json"
    manifest = json.loads(freeze.read_text())
    queries = frozen / "queries.json"
    gold = frozen / "gold.json"
    for path in (queries, gold):
        if manifest["sha256"][path.name] != file_sha256(path):
            raise ValueError("LongMemEval-S scoring inputs differ from their sealed files")
    header, complete, availability, rows, _ = read_replay(
        raw, frozen, manifest, queries, json.loads(queries.read_text())
    )
    if not complete or header["family"] != "longmemeval_s" or header["split"] != "all":
        raise ValueError("Each phase must contain the entire declared LongMemEval-S partition")
    labels = json.loads(gold.read_text())
    ids = {key[0] for key in rows}
    phase_gold = {key: value for key, value in labels.items() if key in ids}
    inventory = {
        key: sum(history[key] for history in availability.values())
        for key in [
            "committed_segments",
            "parsed_segments",
            "indexed_segments",
            "displayable_events",
            "sessions_expected",
            "records_expected",
            "raw_bytes_expected",
            "chunks",
        ]
    }
    return {
        "manifest_sha256": file_sha256(freeze),
        "replay_sha256": file_sha256(raw),
        "manifest": manifest,
        "rows": list(rows.values()),
        "labels": phase_gold,
        "inventory": inventory,
    }


def combine(initial, initial_raw, extension, extension_raw):
    first = open_phase(initial, initial_raw)
    second = open_phase(extension, extension_raw)
    if (
        set(first["labels"]) & set(second["labels"])
        or len(first["labels"]) != 126
        or len(second["labels"]) != 374
    ):
        raise ValueError("The phases overlap or omit registered LongMemEval-S questions")
    if second["manifest"]["previous_freeze_sha256"] != first["manifest_sha256"]:
        raise ValueError("The extension was sealed against another first phase")
    if first["manifest"]["baseline"] != second["manifest"]["baseline"]:
        raise ValueError("The phases used different frozen releases")
    rows = first["rows"] + second["rows"]
    gold = {**first["labels"], **second["labels"]}
    abstention_count = sum(labels["expect_abstain"] for labels in gold.values())
    if len(gold) != 500 or abstention_count != 30:
        raise ValueError("Expected all 500 questions and all 30 abstention controls")
    results = defaultdict(list)
    strata = defaultdict(list)
    for row in rows:
        results[row["arm"]].append(row)
        strata[row["stratum"], row["arm"]].append(row)
    scores = {}
    for arm, trials in sorted(results.items()):
        arm_scores = score_arm(trials, gold, arm)
        arm_scores.pop("latency")  # Report phase wall distributions independently.
        scores[arm] = arm_scores
    return {
        "baseline": first["manifest"]["baseline"],
        "phases": [
            {key: phase[key] for key in ("manifest_sha256", "replay_sha256", "inventory")}
            for phase in (first, second)
        ],
        "inventory": {
            key: value + second["inventory"][key] for key, value in first["inventory"].items()
        },
        "cases": len(gold),
        "answerable": len(gold) - abstention_count,
        "abstention_cases": abstention_count,
        "trials": len(rows),
        "source_sessions_after_question_date": sum(
            labels["later_source_sessions"] for labels in gold.values()
        ),
        "scores": scores,
        "strata": {
            f"{stratum}/{arm}": {
                unit: metric(items, gold, unit, 10, ranked=arm != "product") for unit in GOLD_FIELDS
            }
            for (stratum, arm), items in sorted(strata.items())
        },
        "paired_reformulation": paired(rows, gold),
        "abstention_controls": abstention_controls(rows, gold),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initial", type=Path, required=True)
    parser.add_argument("--initial-replay", type=Path, required=True)
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--extension-replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = combine(args.initial, args.initial_replay, args.extension, args.extension_replay)
    write_private(args.output, summary)
    print(f"Scored {summary['cases']} LongMemEval-S cases across the two frozen phases.")


if __name__ == "__main__":
    main()
