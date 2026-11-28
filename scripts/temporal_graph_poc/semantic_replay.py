"""Separate semantic entry selection from graph traversal over the same facts.

Seed scores come from an independently recorded concept-name reranker call. This
runner opens neither gold nor source answers. Semantic scores are discovery only.
"""

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from corpus import timestamp
from graph import connect
from recall import annotate_coverage, flat_facts, graph_facts


def run(args):
    seed_receipts = [json.loads(l) for l in args.seeds.read_text().splitlines()]
    if seed_receipts[-1].get("type") != "complete":
        raise ValueError("Incomplete semantic seed run")
    seeds = {r["case_id"]: r for r in seed_receipts if r.get("case_id")}
    cases = json.loads(args.questions.read_text())["cases"]
    if set(seeds) != {c["id"] for c in cases}:
        raise ValueError("Semantic seed cases differ")
    db = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    allowed = {
        r[0]
        for r in db.execute(
            "SELECT id FROM concepts WHERE revision=?", (args.revision,)
        )
    }
    with connect(args.env_file) as driver, args.output.open("x") as out:
        args.output.chmod(0o600)
        for case in cases:
            source = seeds[case["id"]]
            if source["status"] != "ok":
                raise ValueError("Fallback is not semantic evidence")
            selected = [c["id"] for c in source["concepts"]]
            if not set(selected) <= allowed or len(selected) > 3:
                raise ValueError("Unrecognized concept selection")
            cutoff = timestamp(case["as_of"])
            for method in ["flat_facts", "graph_facts"]:
                begin = time.perf_counter()
                if method == "flat_facts":
                    result = flat_facts(
                        db,
                        args.revision,
                        case["question"],
                        cutoff,
                        case.get("limit", 8),
                        seed_concepts=selected,
                    )
                else:
                    result = graph_facts(
                        driver,
                        db,
                        args.revision,
                        case["question"],
                        cutoff,
                        case.get("limit", 8),
                        seed_concepts=selected,
                    )
                result = annotate_coverage(db, result, cutoff)
                for c in result["claims"]:
                    if max(c["known_at"], c["valid_at"]) > cutoff or any(
                        s["event_at"] > cutoff for s in c["supports"]
                    ):
                        raise ValueError("Future evidence")
                receipt = {
                    "case_id": case["id"],
                    "trial": 0,
                    "method": method,
                    "as_of": cutoff,
                    "status": "ok",
                    "semantic_seed_latency_ms": source["latency_ms"],
                    "component_latency_ms": (time.perf_counter() - begin) * 1000,
                    "result": result,
                }
                out.write(json.dumps(receipt) + "\n")
                out.flush()
        out.write(
            json.dumps(
                {
                    "type": "complete",
                    "revision": args.revision,
                    "questions_sha256": hashlib.sha256(
                        args.questions.read_bytes()
                    ).hexdigest(),
                    "semantic_seeds_sha256": hashlib.sha256(
                        args.seeds.read_bytes()
                    ).hexdigest(),
                }
            )
            + "\n"
        )
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["seeds", "questions", "corpus", "env-file", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--revision", required=True)
    run(p.parse_args())
