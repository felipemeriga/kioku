"""Compare automatic entity discovery with identical nongraph adjacency control.

Candidates remain unverified reports/requests, with exact original provenance.
Neither scorer gold nor curated semantic claims are opened during this replay.
"""

import argparse
import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from corpus import timestamp
from entity_graph import neighbors
from graph import connect
from recall import annotate_coverage, journal_first


def sqlite_neighbors(db, revision, seeds, cutoff, limit):
    if not seeds:
        return []
    marks = ",".join("?" for _ in seeds)
    entities = defaultdict(set)
    for row in db.execute(
        f"""SELECT e.entity,r.session_id FROM entity_occurrences e JOIN records r ON r.id=e.record_id
      WHERE e.revision=? AND e.record_id IN ({marks}) AND e.event_at<=? AND r.event_at<=?""",
        [revision, *seeds, cutoff, cutoff],
    ):
        entities[row["entity"]].add(row["session_id"])
    scored = {}
    for entity, sessions in entities.items():
        degree = db.execute(
            "SELECT count(DISTINCT canonical_key) FROM entity_occurrences WHERE revision=? AND entity=? AND event_at<=?",
            (revision, entity, cutoff),
        ).fetchone()[0]
        if not 2 <= degree <= 250:
            continue
        for row in db.execute(
            """SELECT r.*,e.canonical_key FROM entity_occurrences e JOIN records r ON r.id=e.record_id
          WHERE e.revision=? AND e.entity=? AND e.event_at<=? AND r.event_at<=? AND r.inherited=0""",
            (revision, entity, cutoff, cutoff),
        ):
            if row["id"] in seeds or row["session_id"] in sessions:
                continue
            entry = scored.setdefault(
                row["id"], {"record": dict(row), "score": 0, "identifiers": []}
            )
            entry["score"] += 1 / degree
            entry["identifiers"].append(entity)
    ordered = sorted(
        scored.values(),
        key=lambda x: (
            -x["score"],
            tuple(-ord(c) for c in x["record"]["event_at"]),
            x["record"]["id"],
        ),
    )
    output = []
    seen = set()
    for row in ordered:
        canonical = row["record"].pop("canonical_key")
        row["record"]["text"] = row["record"]["text"][:12000]
        if canonical not in seen:
            seen.add(canonical)
            output.append(row)
        if len(output) == limit:
            break
    return output


def run(args):
    db = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    projection = json.loads(args.projection.read_text())
    cases = json.loads(args.questions.read_text())["cases"]
    with connect(args.env_file) as driver, args.output.open("x") as out:
        args.output.chmod(0o600)
        for case in cases:
            cutoff = timestamp(case["as_of"])
            begin = time.perf_counter()
            lexical = journal_first(db, case["question"], cutoff, case.get("limit", 8))
            seed_ms = (time.perf_counter() - begin) * 1000
            seeds = [r["id"] for r in lexical.get("records", [])]
            for method, call in [
                (
                    "entity_sqlite",
                    lambda seeds=seeds, cutoff=cutoff: sqlite_neighbors(
                        db, projection["revision"], seeds, cutoff, 4
                    ),
                ),
                (
                    "entity_graph",
                    lambda seeds=seeds, cutoff=cutoff: neighbors(
                        driver, projection["revision"], seeds, cutoff, 4
                    ),
                ),
            ]:
                start = time.perf_counter()
                try:
                    adjacent = call() if seeds else []
                    combined = lexical.get("records", [])[:4] + [
                        r["record"] for r in adjacent
                    ]
                    # Fill remaining space from the same lexical seed result.
                    seen = {r["id"] for r in combined}
                    for r in lexical.get("records", [])[4:]:
                        if len(combined) >= case.get("limit", 8):
                            break
                        if r["id"] not in seen:
                            combined.append(r)
                            seen.add(r["id"])
                    for r in combined:
                        if r["event_at"] > cutoff:
                            raise ValueError("Future candidate")
                        source = db.execute(
                            "SELECT text,source_sha256,byte_offset,byte_length FROM records WHERE id=?",
                            (r["id"],),
                        ).fetchone()
                        if (
                            not source
                            or any(
                                r[k] != source[k]
                                for k in ["source_sha256", "byte_offset", "byte_length"]
                            )
                            or r["text"] != source["text"][:12000]
                        ):
                            raise ValueError("Invalid source candidate")
                    result = annotate_coverage(
                        db,
                        {
                            "records": combined,
                            "hints": lexical.get("hints", []),
                            "discovery_edges": [
                                {
                                    "record_id": a["record"]["id"],
                                    "identifiers": a["identifiers"],
                                    "score": a["score"],
                                }
                                for a in adjacent
                            ],
                            "candidate_semantics": "association only; no status inference",
                        },
                        cutoff,
                    )
                    receipt = {
                        "case_id": case["id"],
                        "trial": 0,
                        "method": method,
                        "status": "ok",
                        "result": result,
                    }
                except Exception as exc:  # noqa: BLE001 - preserve failed replay trials
                    receipt = {
                        "case_id": case["id"],
                        "trial": 0,
                        "method": method,
                        "status": "error",
                        "error_type": type(exc).__name__,
                    }
                receipt.update(
                    seed_latency_ms=seed_ms,
                    neighbor_latency_ms=(time.perf_counter() - start) * 1000,
                )
                out.write(json.dumps(receipt) + "\n")
                out.flush()
                print(
                    json.dumps({k: v for k, v in receipt.items() if k != "result"}),
                    flush=True,
                )
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["corpus", "projection", "questions", "env-file", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    run(p.parse_args())
