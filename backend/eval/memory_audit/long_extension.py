"""Seal the 374 untouched LongMemEval-S histories without changing the initial run."""

import argparse
import hashlib
import json
from pathlib import Path

from .lab import MIGRATION_DIRECTORY
from .public_data import (
    ARMS,
    BASELINE,
    DATASETS,
    READ_COUNT,
    READ_WINDOW,
    RELATED,
    SEED,
    file_sha256,
    freeze_longmem,
    longmem_rows,
    opaque,
    write_private,
)
from .replay import log_line, open_output

FAMILY = "longmemeval_s"
ID_HASHES = {
    "initial": "93541aed41cdb23c5010da8c474102bde8d64f7ab575af4994e01a1211400f33",
    "extension": "4c4aeb25f919dedd4a29d978e037ac24dcde273705e4e11b08f6a2f74ff37986",
    "all": "f038965c54b03632f86a59104dd77848b66e3f80c08d5fbabdd3984d16457811",
}


def id_hash(ids):
    return hashlib.sha256(("\n".join(sorted(ids)) + "\n").encode()).hexdigest()


def freeze(path, initial, output):
    dataset = DATASETS[FAMILY]
    if file_sha256(path) != dataset["sha256"]:
        raise ValueError("The LongMemEval-S file differs from the frozen official release")
    first = json.loads((initial / "freeze.json").read_text())
    if first["baseline"] != BASELINE:
        raise ValueError("The sampled phase ran against a different baseline")
    previous_questions = initial / "queries.json"
    if file_sha256(previous_questions) != first["sha256"]["queries.json"]:
        raise ValueError("The initial frozen case list changed")
    visited = {
        case["case_id"]
        for case in json.loads(previous_questions.read_text())
        if case["family"] == FAMILY
    }
    prior_ids = set()
    selected = {}
    for row in longmem_rows(path):
        source_id = row["question_id"]
        if opaque(FAMILY, source_id, "case") in visited:
            prior_ids.add(source_id)
        else:
            if source_id.endswith("_abs"):
                raise ValueError("The initial sample must already contain every abstention case")
            selected[source_id] = (row["question_type"], "extension")
    hashes = {
        "initial": id_hash(prior_ids),
        "extension": id_hash(selected),
        "all": id_hash(prior_ids | selected.keys()),
    }
    if hashes != ID_HASHES or len(prior_ids) != 126 or len(selected) != 374:
        raise ValueError("The extension population differs from the independently registered IDs")
    if output.resolve().is_relative_to(MIGRATION_DIRECTORY.parents[1]):
        raise ValueError("The frozen corpus must stay outside the worktree")
    output.mkdir(mode=0o700)
    cases, gold = [], {}

    def add(case, labels):
        cases.append(case)
        gold[case["case_id"]] = labels

    with open_output(output / f"{FAMILY}.jsonl") as stream:
        freeze_longmem(path, add, lambda _, row: log_line(stream, row), 0, 0, selected=selected)
    write_private(output / "queries.json", cases)
    write_private(output / "gold.json", gold)
    manifest = {
        "baseline": BASELINE,
        "seed": SEED,
        "datasets": {FAMILY: dataset},
        "cases": len(cases),
        "design": "Disjoint deterministic full-release extension",
        "previous_freeze_sha256": file_sha256(initial / "freeze.json"),
        "independent_source_id_hashes": hashes,
        "policy": {
            "arms": ARMS,
            "related": RELATED,
            "read_window": READ_WINDOW,
            "reads": READ_COUNT,
        },
        "sha256": {file.name: file_sha256(file) for file in sorted(output.iterdir())},
    }
    write_private(output / "freeze.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--initial", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = freeze(args.data, args.initial, args.output)
    print(f"Froze {result['cases']} independently registered extension histories.")


if __name__ == "__main__":
    main()
