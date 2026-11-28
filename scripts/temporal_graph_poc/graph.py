"""Neo4j provenance graph. Explicit relations never imply a successful outcome."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from corpus import timestamp
from neo4j import GraphDatabase


def connect(env_file):
    values = dict(
        line.split("=", 1)
        for line in Path(env_file).read_text().splitlines()
        if line and not line.startswith("#")
    )
    auth = values["NEO4J_AUTH"].split("/", 1)
    driver = GraphDatabase.driver("bolt://127.0.0.1:17687", auth=tuple(auth))
    driver.verify_connectivity()
    return driver


def execute(driver, query, **parameters):
    rows, _, _ = driver.execute_query(query, parameters_=parameters, database_="neo4j")
    return [row.data() for row in rows]


def initialize(driver):
    for label in ["Session", "Journal", "Record", "Claim", "Concept", "EvidenceObject"]:
        execute(
            driver,
            f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE",
        )
    execute(
        driver,
        "CREATE FULLTEXT INDEX journal_text IF NOT EXISTS FOR (n:Journal) ON EACH [n.title,n.body]",
    )
    execute(
        driver,
        "CREATE FULLTEXT INDEX record_text IF NOT EXISTS FOR (n:Record) ON EACH [n.text]",
    )


def import_journals(driver, private):
    frozen = json.loads((private / "snapshot.json").read_text())
    for name in ["journals.json", "sessions.json"]:
        data = (private / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != frozen["files"][name]["sha256"]:
            raise ValueError("Frozen inventory changed")
    sessions = json.loads((private / "sessions.json").read_text())
    journals = json.loads((private / "journals.json").read_text())
    folders = {row["folder_id"] for row in sessions + journals}
    users = {row["user_id"] for row in sessions + journals}
    if folders != {frozen["folder_id"]} or len(users) != 1:
        raise ValueError("Mixed-scope corpus")
    rows = [
        {
            "id": s["id"],
            "native_id": s["native_session_id"],
            "agent": s["agent"],
            "folder_id": s["folder_id"],
            "gaps_json": json.dumps(s["gaps"]),
            "parent_id": s["parent_session_id"],
        }
        for s in sessions
    ]
    execute(
        driver,
        "UNWIND $rows AS row MERGE (s:Session {id:row.id}) SET s += row",
        rows=rows,
    )
    execute(
        driver,
        "MATCH (s:Session),(p:Session) WHERE s.parent_id=p.id MERGE (s)-[:CHILD_OF]->(p)",
    )
    rows = [
        {
            "id": j["entry_id"],
            "native_session_id": j["session_id"],
            "folder_id": j["folder_id"],
            "captured_at": timestamp(j["captured_at"]),
            "title": j["title"],
            "body": j["body"],
            "snapshot_at": frozen["frozen_at"],
            "corpus_snapshot_sha256": hashlib.sha256(
                (private / "snapshot.json").read_bytes()
            ).hexdigest(),
            "historical_revision_verified": False,
        }
        for j in journals
    ]
    execute(
        driver,
        "UNWIND $rows AS row MERGE (j:Journal {id:row.id}) SET j += row",
        rows=rows,
    )
    execute(
        driver,
        "MATCH (j:Journal),(s:Session) WHERE j.native_session_id=s.native_id MERGE (j)-[:REPORTED_IN]->(s)",
    )
    return execute(driver, "MATCH (n) RETURN labels(n)[0] AS label,count(*) AS count")


def import_records(driver, db_path):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    execute(
        driver,
        "CREATE INDEX evidence_sha IF NOT EXISTS FOR (o:EvidenceObject) ON (o.session_id,o.sha256)",
    )
    execute(
        driver,
        "CREATE INDEX record_call IF NOT EXISTS FOR (r:Record) ON (r.session_id,r.call_id)",
    )
    execute(driver, "CALL db.awaitIndexes(60)")
    for table in ["objects", "records"]:
        started = time.perf_counter()
        imported = 0
        cursor = db.execute(f"SELECT * FROM {table}")
        while batch := cursor.fetchmany(300):
            rows = [dict(row) for row in batch]
            if table == "objects":
                for row in rows:
                    row["id"] = row["session_id"] + ":" + row["id"]
                execute(
                    driver,
                    "UNWIND $rows AS row MERGE (o:EvidenceObject {id:row.id}) SET o += row",
                    rows=rows,
                )
            else:
                for row in rows:
                    row["text"] = row["text"][:12000]
                execute(
                    driver,
                    "UNWIND $rows AS row MERGE (r:Record {id:row.id}) SET r += row WITH r,row OPTIONAL MATCH (r)-[old:ARCHIVED_IN]->() DELETE old WITH DISTINCT r,row MATCH (s:Session {id:row.session_id}) MERGE (r)-[:IN_SESSION]->(s) WITH r,row MATCH (o:EvidenceObject {id:row.session_id+':'+row.object_id}) MERGE (r)-[:ARCHIVED_IN]->(o)",
                    rows=rows,
                )
            imported += len(rows)
            if imported % 15000 == 0:
                print(
                    json.dumps(
                        {
                            "table": table,
                            "imported": imported,
                            "elapsed_seconds": time.perf_counter() - started,
                        }
                    ),
                    flush=True,
                )
    links = [dict(row) for row in db.execute("SELECT * FROM journal_links")]
    execute(
        driver,
        "UNWIND $rows AS row MATCH (j:Journal {id:row.journal_id}),(r:Record {id:row.start_id}) MERGE (j)-[:WINDOW_START]->(r)",
        rows=links,
    )
    execute(
        driver,
        "UNWIND $rows AS row MATCH (j:Journal {id:row.journal_id}),(r:Record {id:row.end_id}) MERGE (j)-[:WINDOW_END]->(r)",
        rows=links,
    )
    # Calls/results are evidence of a command and its response, not of the
    # truth of prose emitted by the command. Apply both node cutoffs at recall.
    calls = db.execute(
        "SELECT DISTINCT session_id,call_id FROM records WHERE event_type='tool_call' AND call_id IS NOT NULL"
    )
    while batch := calls.fetchmany(300):
        execute(
            driver,
            "UNWIND $rows AS row MATCH (a:Record {session_id:row.session_id,call_id:row.call_id}) WHERE a.event_type='tool_call' OPTIONAL MATCH (a)-[old:HAS_RESULT]->() DELETE old WITH DISTINCT a,row MATCH (b:Record {session_id:row.session_id,call_id:row.call_id}) WHERE b.event_type='tool_result' AND b.stream_id=a.stream_id AND b.generation=a.generation AND b.sequence>a.sequence MERGE (a)-[:HAS_RESULT]->(b)",
            rows=[dict(row) for row in batch],
        )
    db.close()
    return execute(driver, "MATCH (n) RETURN labels(n)[0] AS label,count(*) AS count")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", type=Path, required=True)
    parser.add_argument("--records", type=Path)
    args = parser.parse_args()
    with connect(args.private_dir / "neo4j.env") as driver:
        initialize(driver)
        print(json.dumps(import_journals(driver, args.private_dir)))
        if args.records:
            print(json.dumps(import_records(driver, args.records)))
