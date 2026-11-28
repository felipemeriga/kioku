"""Bounded concurrent read-only graph replay over frozen real questions.

This measures component stability under load, not model answers or production
throughput. Every worker uses its own read-only SQLite connection.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from corpus import timestamp
from graph import connect
from recall import graph_facts


def run(args):
    cases = json.loads(args.questions.read_text())["cases"]
    lock = threading.Lock()
    counts = {"queries": 0, "failures": 0}
    begin = time.monotonic()
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
                    "duration_seconds": args.duration_seconds,
                    "concurrency": args.concurrency,
                    "interval_seconds": args.interval_seconds,
                    "questions_sha256": hashlib.sha256(
                        args.questions.read_bytes()
                    ).hexdigest(),
                    "revision": args.revision,
                    "implementation_sha256": hashlib.sha256(
                        Path(__file__).with_name("recall.py").read_bytes()
                    ).hexdigest(),
                }
            )
            + "\n"
        )
        out.flush()

        def worker(worker_id):
            db = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            sequence = 0
            cache = {}
            try:
                while time.monotonic() - begin < args.duration_seconds:
                    started = time.monotonic()
                    case = cases[(worker_id + sequence) % len(cases)]
                    cutoff = timestamp(case["as_of"])
                    row = {
                        "worker": worker_id,
                        "sequence": sequence,
                        "case_id": case["id"],
                    }
                    try:
                        result = graph_facts(
                            driver,
                            db,
                            args.revision,
                            case["question"],
                            cutoff,
                            case.get("limit", 8),
                        )
                        claims = result["claims"]
                        ids = [c["id"] for c in claims]
                        if len(ids) != len(set(ids)):
                            raise ValueError("duplicate_claims")
                        for c in claims:
                            if max(c["known_at"], c["valid_at"]) > cutoff:
                                raise ValueError("future_claim")
                            for s in c["supports"]:
                                if s["record_id"] not in cache:
                                    cache[s["record_id"]] = db.execute(
                                        "SELECT event_at,text,source_sha256,byte_offset,byte_length FROM records WHERE id=?",
                                        (s["record_id"],),
                                    ).fetchone()
                                source = cache[s["record_id"]]
                                if (
                                    not source
                                    or source["event_at"] > cutoff
                                    or s["quote"] not in source["text"]
                                    or any(
                                        s[k] != source[k]
                                        for k in [
                                            "source_sha256",
                                            "byte_offset",
                                            "byte_length",
                                        ]
                                    )
                                ):
                                    raise ValueError("invalid_original_support")
                        if any(e["known_at"] > cutoff for e in result["relations"]):
                            raise ValueError("future_relation")
                        if any(
                            h["published_at"] > cutoff or h["captured_at"] > cutoff
                            for h in result["hints"]
                        ):
                            raise ValueError("future_journal")
                        row.update(
                            status="ok",
                            claims=len(claims),
                            result_fingerprint=hashlib.sha256(
                                json.dumps(result, sort_keys=True).encode()
                            ).hexdigest(),
                        )
                    except Exception as exc:  # noqa: BLE001 - preserve all failed load trials
                        row.update(status="error", error_type=type(exc).__name__)
                        if isinstance(exc, ValueError):
                            row["assertion"] = str(exc)
                    row["latency_ms"] = (time.monotonic() - started) * 1000
                    with lock:
                        counts["queries"] += 1
                        counts["failures"] += row["status"] == "error"
                        out.write(json.dumps(row) + "\n")
                        out.flush()
                    sequence += 1
                    time.sleep(
                        max(0, args.interval_seconds - (time.monotonic() - started))
                    )
            finally:
                db.close()

        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            jobs = [pool.submit(worker, i) for i in range(args.concurrency)]
            for job in jobs:
                job.result()
        final = {"type": "complete", "wall_seconds": time.monotonic() - begin, **counts}
        out.write(json.dumps(final) + "\n")
        out.flush()
        print(json.dumps(final))
    if counts["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["corpus", "questions", "env-file", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--duration-seconds", type=float, default=600)
    p.add_argument("--interval-seconds", type=float, default=0.25)
    p.add_argument("--concurrency", type=int, default=4)
    args = p.parse_args()
    if (
        not 1 <= args.concurrency <= 8
        or args.duration_seconds <= 0
        or args.interval_seconds <= 0
    ):
        p.error("Invalid load bounds")
    run(args)
