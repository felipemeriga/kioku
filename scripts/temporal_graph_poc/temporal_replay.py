"""Audit every curated real claim at exact original-knowledge boundaries.

This validates temporal retrieval contracts, not semantic extraction accuracy.
The large result budget deliberately isolates cutoff behavior from ranking.
"""

import argparse
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

from graph import connect
from recall import flat_facts, graph_facts


def run(args):
    db = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    claims = [
        json.loads(r[0])
        for r in db.execute(
            "SELECT payload FROM claims WHERE revision=?", (args.revision,)
        )
    ]
    concepts = {
        r["id"]: json.loads(r["payload"])
        for r in db.execute(
            "SELECT id,payload FROM concepts WHERE revision=?", (args.revision,)
        )
    }
    checks = []
    with connect(args.env_file) as driver:
        for claim in claims:
            question = concepts[claim["concepts"][0]]["name"]
            boundary = max(claim["known_at"], claim["valid_at"])
            for offset in [-1, 0]:
                cutoff = (
                    datetime.fromisoformat(boundary) + timedelta(microseconds=offset)
                ).isoformat(timespec="microseconds")
                for method, call in [
                    (
                        "flat_facts",
                        lambda question=question, cutoff=cutoff: flat_facts(
                            db, args.revision, question, cutoff, len(claims)
                        ),
                    ),
                    (
                        "graph_facts",
                        lambda question=question, cutoff=cutoff: graph_facts(
                            driver, db, args.revision, question, cutoff, len(claims)
                        ),
                    ),
                ]:
                    begin = time.perf_counter()
                    result = call()
                    keys = {c["key"] for c in result["claims"]}
                    errors = []
                    if (claim["key"] in keys) != (offset == 0):
                        errors.append("boundary_inclusion")
                    for c in result["claims"]:
                        if max(c["known_at"], c["valid_at"]) > cutoff:
                            errors.append("future_claim")
                        if any(s["event_at"] > cutoff for s in c["supports"]):
                            errors.append("future_support")
                    if any(e["known_at"] > cutoff for e in result["relations"]):
                        errors.append("future_relation")
                    checks.append(
                        {
                            "claim": claim["key"],
                            "method": method,
                            "offset_microseconds": offset,
                            "cutoff": cutoff,
                            "errors": errors,
                            "latency_ms": (time.perf_counter() - begin) * 1000,
                        }
                    )
    report = {
        "revision": args.revision,
        "description": __doc__,
        "checks": checks,
        "failures": sum(bool(c["errors"]) for c in checks),
        "status": "ok" if all(not c["errors"] for c in checks) else "failed",
    }
    with args.output.open("x") as out:
        out.write(json.dumps(report, indent=2) + "\n")
    args.output.chmod(0o600)
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}))
    db.close()
    if report["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--env-file", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
