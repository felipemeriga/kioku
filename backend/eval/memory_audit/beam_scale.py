"""Freeze bounded complete conversations from the larger published BEAM splits."""

import argparse
from pathlib import Path

from .public_data import file_sha256, stable_priority
from .supplemental import freeze_family, parse_beam

BEAM = "3205395e897e7318c7b094ef4e6047b9b82dbb03"
LARGE_DATASETS = {
    "beam_500k_sample": {
        "file": "beam-500k.parquet",
        "revision": BEAM,
        "sha256": "af05921c979355038e1761b7cde3d2dd713200dd3071b278de0200f6c7f30122",
        "projection": "Four hash-selected complete conversations with all their probes.",
        "selected": 4,
    },
    "beam_1m_sample": {
        "file": "beam-1m.parquet",
        "revision": BEAM,
        "sha256": "41b5acbbb55a586b1305514ef9d9fb03365d9b3331b598a1c2dd7603d93ef533",
        "projection": "Four hash-selected complete conversations with all their probes.",
        "selected": 4,
    },
    "beam_10m_sample": {
        "file": "beam-10m-0.parquet",
        "other_files": {
            "beam-10m-1.parquet": (
                "a4f13fe25af51d57405ae41008689c31d1421377f3efde56a024b441deb2ee65"
            ),
        },
        "revision": "9b2096193fe74e2837e4713e483351e19817773c",
        "sha256": "31d96fd47ec56221d202e68792f26c00e49467dd4b36ee105c36ebd19ef78ad5",
        "projection": "One complete conversation and its probes, preserving published batch dates.",
        "selected": 1,
    },
}


def selected_chats(paths, size, nested):
    from pyarrow import parquet

    readers = [parquet.ParquetFile(path) for path in paths]
    ids = [
        row["conversation_id"]
        for reader in readers
        for metadata in reader.iter_batches(columns=["conversation_id"])
        for row in metadata.to_pylist()
    ]
    if len(set(ids)) != len(ids):
        raise ValueError("Published conversation IDs must be distinct within a split")
    selected = set(sorted(ids, key=stable_priority)[:size])
    consumed = set()
    for reader in readers:
        ids_in_file = reader.read(columns=["conversation_id"]).column("conversation_id").to_pylist()
        columns = ["conversation_id", "chat", "probing_questions"]
        if selected.isdisjoint(ids_in_file):
            continue
        for index, batch in enumerate(reader.iter_batches(batch_size=1, columns=columns)):
            identity = ids_in_file[index]
            if identity not in selected:
                continue
            selected_row = batch.to_pylist()[0]
            if nested:
                # In the 10M release each plan holds dated batches with turn
                # groups. Archive each batch as one session without losing turns.
                selected_row["chat"] = [
                    [turn for group in dated_batch["turns"] for turn in group]
                    for plan in selected_row["chat"]
                    for value in plan.values()
                    if value is not None
                    for dated_batch in value
                ]
            consumed.add(identity)
            yield selected_row
    if consumed != selected:
        raise ValueError("Some selected full conversations were absent")


def freeze_scale(family, directory, output):
    spec = LARGE_DATASETS[family]
    other = spec.get("other_files", {})
    for name, digest in other.items():
        if file_sha256(directory / name) != digest:
            raise ValueError("An additional BEAM shard differs from its frozen revision")

    def load(path, stream, add_case):
        paths = [path, *(directory / name for name in other)]
        rows = selected_chats(paths, spec["selected"], family == "beam_10m_sample")
        parse_beam(rows, stream, add_case, family=family, revision=spec["revision"])

    return freeze_family(family, spec, directory, output, load)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=sorted(LARGE_DATASETS), required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record = freeze_scale(args.family, args.data, args.output)
    print(f"Froze {record['cases']} probes from complete {args.family} conversations.")


if __name__ == "__main__":
    main()
