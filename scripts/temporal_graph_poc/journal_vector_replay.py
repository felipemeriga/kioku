"""Frozen semantic journal hints and exact original-window graph/SQL controls.

Vectors are discovery only. Publication and native-record cutoffs are independent.
A journal without originals remains a revisable hint, never verified evidence.
"""

import argparse
import hashlib
import json
import math
import sqlite3
import time
from pathlib import Path

from corpus import timestamp
from graph import connect, execute
from recall import annotate_coverage


def vector(text, receipt):
    if hashlib.sha256(text.encode()).hexdigest() != receipt["text_sha256"]:
        raise ValueError("Vector text differs from frozen source")
    values = receipt["vector"]
    if len(values) != 1024 or any(not math.isfinite(v) for v in values):
        raise ValueError("Invalid embedding")
    norm = math.sqrt(sum(v * v for v in values))
    if not norm:
        raise ValueError("Empty embedding")
    return [v / norm for v in values]


def sql_window(db, journal_id, cutoff):
    return [
        dict(r)
        for r in db.execute(
            """SELECT r.* FROM journal_links l
      JOIN journals j ON j.id=l.journal_id JOIN journal_publications p ON p.day=j.day
      JOIN records a ON a.id=l.start_id JOIN records b ON b.id=l.end_id
      JOIN sessions s ON s.id=a.session_id AND s.native_id=j.session_id
      JOIN records r ON r.session_id=a.session_id AND r.stream_id=a.stream_id AND r.generation=a.generation
      WHERE j.id=? AND j.captured_at<=? AND p.published_at<=?
        AND a.session_id=b.session_id AND a.stream_id=b.stream_id AND a.generation=b.generation
        AND a.sequence<=b.sequence AND r.sequence BETWEEN a.sequence AND b.sequence
        AND r.event_at<=? AND r.displayable=1 AND r.inherited=0 AND coalesce(r.channel,'')<>'analysis'
      ORDER BY CASE r.role WHEN 'assistant' THEN 0 WHEN 'tool' THEN 1 ELSE 2 END,r.sequence DESC LIMIT 8""",
            (journal_id, cutoff, cutoff, cutoff),
        )
    ]


def graph_window(driver, journal_id, cutoff, snapshot):
    return [
        r["record"]
        for r in execute(
            driver,
            """MATCH(j:Journal {id:$id,corpus_snapshot_sha256:$snapshot})-[:WINDOW_START]->(a:Record),
       (j)-[:WINDOW_END]->(b:Record),(a)-[:IN_SESSION]->(s:Session)
      WHERE j.captured_at<=$cutoff AND j.published_at<=$cutoff AND s.native_id=j.native_session_id
        AND a.session_id=b.session_id AND a.stream_id=b.stream_id AND a.generation=b.generation AND a.sequence<=b.sequence
      MATCH(r:Record {session_id:a.session_id,stream_id:a.stream_id,generation:a.generation})
      WHERE r.sequence>=a.sequence AND r.sequence<=b.sequence AND r.event_at<=$cutoff
        AND r.displayable=1 AND r.inherited=0 AND coalesce(r.channel,'')<>'analysis'
      RETURN properties(r) AS record ORDER BY CASE r.role WHEN 'assistant' THEN 0 WHEN 'tool' THEN 1 ELSE 2 END,r.sequence DESC LIMIT 8""",
            id=journal_id,
            cutoff=cutoff,
            snapshot=snapshot,
        )
    ]


def select_records(windows, limit):
    # Round-robin over hints avoids letting a long first window consume the budget.
    result = []
    seen = set()
    for index in range(8):
        for rows in windows:
            if index >= len(rows):
                continue
            record = dict(rows[index])
            record["text"] = record["text"][:12000]
            key = (
                record["session_id"],
                record["role"],
                record["event_type"],
                record["event_at"][:19],
                record["text"],
            )
            if key not in seen:
                result.append(record)
                seen.add(key)
                if len(result) == limit:
                    return result
    return result


def run(args):
    receipts = [json.loads(l) for l in args.vectors.read_text().splitlines()]
    if receipts[-1].get("type") != "complete":
        raise ValueError("Incomplete vector receipt")
    documents = {
        r["id"]: r
        for r in receipts
        if r.get("type") == "vector" and r["kind"] == "documents"
    }
    queries = {
        r["id"]: r
        for r in receipts
        if r.get("type") == "vector" and r["kind"] == "queries"
    }
    db = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    snapshot = json.loads(
        db.execute("SELECT value FROM metadata WHERE key='snapshot_sha256'").fetchone()[
            0
        ]
    )
    journals = [
        dict(r)
        for r in db.execute(
            "SELECT j.*,p.published_at,p.revision AS publication_revision,p.sha256 AS publication_sha256 FROM journals j JOIN journal_publications p ON p.day=j.day"
        )
    ]
    if set(documents) != {r["id"] for r in journals}:
        raise ValueError("Embedding corpus differs")
    for j in journals:
        j["vector"] = vector(j["title"] + "\n\n" + j["body"], documents[j["id"]])
    cases = json.loads(args.questions.read_text())["cases"]
    with connect(args.env_file) as driver, args.output.open("x") as out:
        args.output.chmod(0o600)
        for case in cases:
            begin = time.perf_counter()
            cutoff = timestamp(case["as_of"])
            query = vector(case["question"], queries[case["id"]])
            eligible = [
                {k: v for k, v in j.items() if k != "vector"}
                | {
                    "vector_score": sum(
                        a * b for a, b in zip(j["vector"], query, strict=True)
                    )
                }
                for j in journals
                if j["published_at"] <= cutoff and j["captured_at"] <= cutoff
            ]
            hints = sorted(eligible, key=lambda j: (-j["vector_score"], j["id"]))[:8]
            ranking_ms = (time.perf_counter() - begin) * 1000
            sql_ids = None
            for method in ["vector_windows_sqlite", "vector_windows_graph"]:
                start = time.perf_counter()
                windows = [
                    sql_window(db, h["id"], cutoff)
                    if method.endswith("sqlite")
                    else graph_window(driver, h["id"], cutoff, snapshot)
                    for h in hints
                ]
                records = select_records(windows, case.get("limit", 8))
                for r in records:
                    source = db.execute(
                        "SELECT * FROM records WHERE id=?", (r["id"],)
                    ).fetchone()
                    if (
                        r["event_at"] > cutoff
                        or any(
                            r[k] != source[k]
                            for k in ["source_sha256", "byte_offset", "byte_length"]
                        )
                        or r["text"] != source["text"][:12000]
                    ):
                        raise ValueError("Invalid original window candidate")
                ids = [r["id"] for r in records]
                if sql_ids is not None and ids != sql_ids:
                    raise ValueError("Graph and SQL pointer expansion differ")
                sql_ids = ids
                result = annotate_coverage(
                    db,
                    {
                        "hints": hints,
                        "records": records,
                        "window_candidate_count": sum(len(w) for w in windows),
                        "candidate_semantics": "semantic hints and source windows, no inferred status",
                    },
                    cutoff,
                )
                row = {
                    "case_id": case["id"],
                    "trial": 0,
                    "method": method,
                    "status": "ok",
                    "as_of": cutoff,
                    "ranking_latency_ms": ranking_ms,
                    "expansion_latency_ms": (time.perf_counter() - start) * 1000,
                    "result": result,
                }
                out.write(json.dumps(row) + "\n")
                out.flush()
                print(
                    json.dumps({k: v for k, v in row.items() if k != "result"}),
                    flush=True,
                )
        out.write(
            json.dumps(
                {
                    "type": "complete",
                    "questions_sha256": hashlib.sha256(
                        args.questions.read_bytes()
                    ).hexdigest(),
                    "vectors_sha256": hashlib.sha256(
                        args.vectors.read_bytes()
                    ).hexdigest(),
                    "corpus_snapshot_sha256": snapshot,
                }
            )
            + "\n"
        )
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["corpus", "vectors", "questions", "env-file", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    run(p.parse_args())
