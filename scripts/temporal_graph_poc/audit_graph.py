"""Compare every imported record and exact archive locator with the frozen cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path

from graph import connect, execute


def audit(corpus, env_file, batch_size=1500):
    db = sqlite3.connect(f"file:{corpus}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    sessions = [row[0] for row in db.execute("SELECT id FROM sessions")]
    expected_count = db.execute("SELECT count(*) FROM records").fetchone()[0]
    cursor = ""
    checked = 0
    failures = []
    fingerprint = hashlib.sha256()
    begin = time.perf_counter()
    with connect(env_file) as driver:
        while True:
            rows = execute(
                driver,
                """MATCH(r:Record) WHERE r.session_id IN $sessions AND r.id>$cursor
              WITH r ORDER BY r.id LIMIT $limit
              OPTIONAL MATCH (r)-[:ARCHIVED_IN]->(o:EvidenceObject)
              RETURN properties(r) AS record,collect({id:o.id,sha256:o.sha256}) AS objects ORDER BY record.id""",
                sessions=sessions,
                cursor=cursor,
                limit=batch_size,
            )
            if not rows:
                break
            ids = [row["record"]["id"] for row in rows]
            expected = {
                row["id"]: dict(row)
                for row in db.execute(
                    "SELECT * FROM records WHERE id IN ("
                    + ",".join("?" for _ in ids)
                    + ")",
                    ids,
                )
            }
            for row in rows:
                actual = row["record"]
                rid = actual["id"]
                original = expected.get(rid)
                if not original:
                    failures.append({"id": rid, "reason": "unexpected_record"})
                    continue
                for field, value in original.items():
                    value = value[:12000] if field == "text" else value
                    if actual.get(field) != value:
                        failures.append(
                            {"id": rid, "reason": "field_mismatch", "field": field}
                        )
                objects = row["objects"]
                if (
                    len(objects) != 1
                    or objects[0]["id"]
                    != original["session_id"] + ":" + original["object_id"]
                    or objects[0]["sha256"] != original["source_sha256"]
                ):
                    failures.append({"id": rid, "reason": "archive_locator_mismatch"})
                fingerprint.update(
                    json.dumps(actual, sort_keys=True, separators=(",", ":")).encode()
                )
                checked += 1
            cursor = ids[-1]
            if checked % 15000 == 0:
                print(
                    json.dumps({"records_checked": checked, "failures": len(failures)}),
                    flush=True,
                )
        invalid_calls = execute(
            driver,
            """MATCH(a:Record)-[edge:HAS_RESULT]->(b:Record)
          WHERE a.session_id IN $sessions AND (a.session_id<>b.session_id OR a.stream_id<>b.stream_id
            OR a.generation<>b.generation OR a.sequence>=b.sequence
            OR a.event_type<>'tool_call' OR b.event_type<>'tool_result' OR a.call_id<>b.call_id)
          RETURN count(edge) AS count""",
            sessions=sessions,
        )[0]["count"]
        unexpected = execute(
            driver,
            """MATCH(r:Record) WHERE r.contract_fixture IS NULL
          AND (r.session_id IS NULL OR NOT r.session_id IN $sessions) RETURN count(r) AS count""",
            sessions=sessions,
        )[0]["count"]
    db.close()
    return {
        "records_checked": checked,
        "expected_records": expected_count,
        "record_field_failures": len(failures),
        "failure_details": failures,
        "invalid_call_result_pairs": invalid_calls,
        "unexpected_records": unexpected,
        "projection_fingerprint": fingerprint.hexdigest(),
        "elapsed_seconds": time.perf_counter() - begin,
        "status": "ok"
        if checked == expected_count
        and not failures
        and not invalid_calls
        and not unexpected
        else "failed",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.corpus, args.env_file)
    with os.fdopen(
        os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as out:
        json.dump(result, out, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != "failure_details"}))
    raise SystemExit(0 if result["status"] == "ok" else 1)
