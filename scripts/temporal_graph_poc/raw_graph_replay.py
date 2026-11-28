"""Whole-corpus Neo4j original-text availability control.

This is not the session-seeded lexical baseline and is not a matched latency
comparison. It tests whether omitted facts remain searchable in original nodes.
No curated facts or answer annotations are loaded by this caller.
"""

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from corpus import timestamp
from graph import connect, execute
from recall import annotate_coverage, fts_query


def run(args):
    raw = args.questions.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.sha256:
        raise ValueError("Question manifest changed")
    db = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    sessions = [r[0] for r in db.execute("SELECT id FROM sessions")]
    with connect(args.env_file) as driver, args.output.open("x") as out:
        args.output.chmod(0o600)
        for case in json.loads(raw)["cases"]:
            before = time.perf_counter()
            cutoff = timestamp(case["as_of"])
            candidates = execute(
                driver,
                """CALL db.index.fulltext.queryNodes('record_text',$query) YIELD node,score
              WHERE node.session_id IN $sessions AND node.event_at<=$cutoff AND node.inherited=0 AND node.displayable=1 AND coalesce(node.channel,'')<>'analysis'
              RETURN properties(node) AS record,score ORDER BY score DESC,node.event_at DESC,node.id LIMIT $limit""",
                query=fts_query(case["question"]),
                sessions=sessions,
                cutoff=cutoff,
                limit=case.get("limit", 8) * 20,
            )
            records = []
            seen = set()
            for item in candidates:
                r = item["record"]
                key = (
                    r["session_id"],
                    r["role"],
                    r["event_type"],
                    r["event_at"][:19],
                    r["text"],
                )
                if key in seen:
                    continue
                seen.add(key)
                records.append(r)
                source = db.execute(
                    "SELECT * FROM records WHERE id=?", (r["id"],)
                ).fetchone()
                if (
                    not source
                    or r["text"] != source["text"][:12000]
                    or any(
                        r[k] != source[k]
                        for k in ["source_sha256", "byte_offset", "byte_length"]
                    )
                ):
                    raise ValueError("Original projection mismatch")
                if len(records) >= case.get("limit", 8):
                    break
            result = annotate_coverage(
                db,
                {
                    "records": records,
                    "hints": [],
                    "scope_note": "full frozen authorized corpus, not journal-seeded sessions",
                },
                cutoff,
            )
            row = {
                "case_id": case["id"],
                "trial": 0,
                "method": "raw_graph_fulltext",
                "status": "ok",
                "as_of": cutoff,
                "latency_ms": (time.perf_counter() - before) * 1000,
                "result": result,
            }
            out.write(json.dumps(row) + "\n")
            out.flush()
        out.write(
            json.dumps({"type": "complete", "questions_sha256": args.sha256}) + "\n"
        )
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["corpus", "questions", "env-file", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--sha256", required=True)
    run(p.parse_args())
