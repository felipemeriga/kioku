"""Long-running, read-only source/temporal conformance checks on the real corpus.

This measures provenance and cutoff safety, not answer accuracy. Suspended-machine
time does not count toward the requested testing duration. Receipts stay private.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from corpus import timestamp
from graph import connect, execute
from neo4j.exceptions import Neo4jError
from recall import graph_facts


def run(args):
    db = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    candidates = db.execute(
        "SELECT id,event_at FROM records WHERE displayable=1 AND event_at IS NOT NULL"
    ).fetchall()
    if not candidates:
        raise ValueError("No timed original evidence")
    randomizer = random.Random(args.seed)
    questions = json.loads(args.questions.read_text())["cases"]
    verified_objects = {}
    started = time.monotonic()
    tested_seconds = 0.0
    iteration = 0
    failures = 0
    claims_checked = 0
    with (
        connect(args.env_file) as driver,
        os.fdopen(
            os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as out,
    ):
        out.write(
            json.dumps(
                {
                    "type": "start",
                    "at": datetime.now().astimezone().isoformat(),
                    "requested_seconds": args.duration_seconds,
                    "seed": args.seed,
                    "revision": args.revision,
                    "implementation_sha256": {
                        name: hashlib.sha256(
                            Path(__file__).with_name(name).read_bytes()
                        ).hexdigest()
                        for name in ["soak.py", "recall.py", "graph.py", "facts.py"]
                    },
                    "question_sha256": hashlib.sha256(
                        args.questions.read_bytes()
                    ).hexdigest(),
                    "corpus_snapshot_sha256": json.loads(
                        db.execute(
                            "SELECT value FROM metadata WHERE key='snapshot_sha256'"
                        ).fetchone()[0]
                    ),
                    "metric": "source provenance and historical cutoff conformance; not answer accuracy",
                }
            )
            + "\n"
        )
        out.flush()
        while tested_seconds < args.duration_seconds:
            begin = time.monotonic()
            stage = "record_lookup"
            chosen = randomizer.choice(candidates)
            source = db.execute(
                "SELECT * FROM records WHERE id=?", (chosen["id"],)
            ).fetchone()
            delta = randomizer.choice([-1, 0, 1, 86400000000])
            cutoff = (
                datetime.fromisoformat(chosen["event_at"])
                + timedelta(microseconds=delta)
            ).isoformat(timespec="microseconds")
            receipt = {
                "iteration": iteration,
                "record_id": chosen["id"],
                "cutoff": cutoff,
                "delta_microseconds": delta,
            }
            try:
                actual = execute(
                    driver,
                    "MATCH(r:Record {id:$id}) WHERE r.event_at<=$cutoff MATCH(r)-[:ARCHIVED_IN]->(o:EvidenceObject) RETURN r.id AS id,r.event_at AS event_at,r.source_sha256 AS sha256,r.object_id AS object_id,r.byte_offset AS byte_offset,r.byte_length AS byte_length,o.id AS object_graph_id,o.sha256 AS object_sha256",
                    id=source["id"],
                    cutoff=cutoff,
                )
                assert len(actual) == (0 if delta < 0 else 1), (
                    "record_cutoff_or_duplicate_source"
                )
                if actual:
                    row = actual[0]
                    assert (
                        row["sha256"] == source["source_sha256"] == row["object_sha256"]
                    ), "source_hash_mismatch"
                    assert (
                        row["object_graph_id"]
                        == source["session_id"] + ":" + source["object_id"]
                    ), "wrong_source_object"
                    assert (row["byte_offset"], row["byte_length"]) == (
                        source["byte_offset"],
                        source["byte_length"],
                    ), "wrong_byte_locator"
                if iteration % 10 == 0:
                    stage = "original_bytes"
                    checksum = source["source_sha256"]
                    raw = (args.object_cache / (checksum + ".jsonl")).read_bytes()
                    assert hashlib.sha256(raw).hexdigest() == checksum, (
                        "stored_original_changed"
                    )
                    record = raw[
                        source["byte_offset"] : source["byte_offset"]
                        + source["byte_length"]
                    ]
                    assert record.endswith(b"\n") and isinstance(
                        json.loads(record), dict
                    ), "invalid_original_locator"
                    verified_objects[checksum] = True
                if iteration % 3 == 0:
                    stage = "claim_cutoff"
                    case = randomizer.choice(questions)
                    # Mix historical boundary probes with the case's actual date.
                    claim_cutoff = cutoff if iteration % 2 else case["as_of"]
                    claim_cutoff = timestamp(claim_cutoff)
                    result = graph_facts(
                        driver,
                        db,
                        args.revision,
                        case["question"],
                        claim_cutoff,
                        case.get("limit", 8),
                        case.get("environment"),
                    )
                    ids = [c["id"] for c in result["claims"]]
                    assert len(ids) == len(set(ids)), "duplicate_claims"
                    for claim in result["claims"]:
                        assert (
                            claim["known_at"] <= claim_cutoff
                            and claim["valid_at"] <= claim_cutoff
                        ), "future_claim"
                        for support in claim["supports"]:
                            original = db.execute(
                                "SELECT event_at,text,source_sha256 FROM records WHERE id=?",
                                (support["record_id"],),
                            ).fetchone()
                            assert original and original["event_at"] <= claim_cutoff, (
                                "future_or_unknown_support"
                            )
                            assert support["quote"] in original["text"], (
                                "unsupported_quote"
                            )
                            assert (
                                support["source_sha256"] == original["source_sha256"]
                            ), "support_hash_mismatch"
                        claims_checked += 1
                receipt["status"] = "ok"
            except (
                AssertionError,
                sqlite3.Error,
                Neo4jError,
                OSError,
                ValueError,
            ) as exc:
                failures += 1
                receipt.update(
                    status="error", stage=stage, error_type=type(exc).__name__
                )
                if isinstance(exc, AssertionError):
                    receipt["assertion"] = str(exc)
            receipt["latency_ms"] = (time.monotonic() - begin) * 1000
            out.write(json.dumps(receipt) + "\n")
            out.flush()
            iteration += 1
            time.sleep(max(0, args.interval_seconds - (time.monotonic() - begin)))
            # Cap any long inter-probe gap: sleeping/suspended Macs cannot pass a
            # four-hour run by resuming just once after the deadline.
            tested_seconds += min(time.monotonic() - begin, args.interval_seconds * 2)
            if iteration % 120 == 0:
                print(
                    json.dumps(
                        {
                            "iterations": iteration,
                            "tested_seconds": round(tested_seconds, 1),
                            "failures": failures,
                            "claims_checked": claims_checked,
                            "objects_verified": len(verified_objects),
                        }
                    ),
                    flush=True,
                )
        terminal = {
            "type": "complete",
            "iterations": iteration,
            "tested_seconds": tested_seconds,
            "wall_seconds": time.monotonic() - started,
            "failures": failures,
            "claims_checked": claims_checked,
            "objects_verified": len(verified_objects),
            "answer_accuracy_established": False,
        }
        out.write(json.dumps(terminal) + "\n")
        out.flush()
        print(json.dumps(terminal), flush=True)
    db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--object-cache", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--interval-seconds", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=20261128)
    args = parser.parse_args()
    if args.duration_seconds <= 0 or args.interval_seconds <= 0:
        parser.error("Durations must be positive")
    run(args)
