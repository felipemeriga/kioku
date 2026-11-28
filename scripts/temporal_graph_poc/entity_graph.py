"""Question-independent identifier graph over native user/assistant messages.

Co-mentions generate discovery candidates only. They never establish causality,
status, supersession or success. No questions, reviewed facts or gold are read
while building this projection. Original nodes and archive bytes stay unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from graph import connect, execute

TOKEN = re.compile(r"`([A-Za-z_][A-Za-z0-9_./:\-]{3,79})`|\b([A-Z][A-Z0-9_]{2,30})\b")


def identifiers(text):
    found = set()
    for match in TOKEN.finditer(text):
        token = next(v for v in match.groups() if v)
        if re.search(r"secret|password|token|access.?key", token, re.IGNORECASE):
            continue
        if not (
            re.search(r"[_/:.]", token)
            or re.search(r"[a-z][A-Z]", token)
            or token.isupper()
        ):
            continue
        if len(token) > 50 or token.count("/") > 4:
            continue
        found.add(token.casefold().rstrip("/"))
    return sorted(found)[:24]


def build(args):
    db = sqlite3.connect(args.corpus)
    db.row_factory = sqlite3.Row
    snapshot = json.loads(
        db.execute("SELECT value FROM metadata WHERE key='snapshot_sha256'").fetchone()[
            0
        ]
    )
    revision = hashlib.sha256(
        (snapshot + Path(__file__).read_text()).encode()
    ).hexdigest()
    db.executescript("""CREATE TABLE IF NOT EXISTS entity_occurrences(revision TEXT,record_id TEXT,entity TEXT,canonical_key TEXT,event_at TEXT,PRIMARY KEY(revision,record_id,entity));
    CREATE INDEX IF NOT EXISTS entity_lookup ON entity_occurrences(revision,entity,event_at);
    CREATE INDEX IF NOT EXISTS entity_source ON entity_occurrences(revision,record_id);""")
    rows = []
    degrees = {}
    for record in db.execute(
        "SELECT id,text,event_at,role FROM records WHERE displayable=1 AND inherited=0 AND event_at IS NOT NULL AND role IN ('user','assistant') AND coalesce(channel,'')<>'analysis'"
    ):
        canonical = hashlib.sha256(
            json.dumps(
                [record["role"], record["event_at"], record["text"]], ensure_ascii=False
            ).encode()
        ).hexdigest()
        for entity in identifiers(record["text"]):
            rows.append((revision, record["id"], entity, canonical, record["event_at"]))
            degrees.setdefault(entity, set()).add(canonical)
    eligible = {entity: len(keys) for entity, keys in degrees.items()}
    rows = [r for r in rows if r[2] in eligible]
    with db:
        db.execute("DELETE FROM entity_occurrences WHERE revision=?", (revision,))
        db.executemany("INSERT INTO entity_occurrences VALUES(?,?,?,?,?)", rows)
    with connect(args.env_file) as driver:
        execute(
            driver,
            "CREATE CONSTRAINT recall_entity_id IF NOT EXISTS FOR (n:RecallEntity) REQUIRE n.id IS UNIQUE",
        )
        entities = [
            {
                "id": revision + ":" + hashlib.sha256(e.encode()).hexdigest(),
                "identifier": e,
                "degree": n,
                "revision": revision,
            }
            for e, n in eligible.items()
        ]
        for start in range(0, len(entities), 500):
            execute(
                driver,
                "UNWIND $rows AS row MERGE(e:RecallEntity {id:row.id}) SET e += row",
                rows=entities[start : start + 500],
            )
        for start in range(0, len(rows), 1000):
            batch = [
                {
                    "record_id": r[1],
                    "entity_id": revision
                    + ":"
                    + hashlib.sha256(r[2].encode()).hexdigest(),
                    "canonical_key": r[3],
                    "known_at": r[4],
                }
                for r in rows[start : start + 1000]
            ]
            execute(
                driver,
                "UNWIND $rows AS row MATCH(r:Record {id:row.record_id}),(e:RecallEntity {id:row.entity_id}) MERGE(r)-[m:MENTIONS]->(e) SET m.canonical_key=row.canonical_key,m.known_at=row.known_at",
                rows=batch,
            )
        actual = execute(
            driver,
            "MATCH(r:Record)-[m:MENTIONS]->(e:RecallEntity {revision:$revision}) RETURN count(m) AS mentions,count(DISTINCT e) AS entities",
            revision=revision,
        )[0]
    expected = {"mentions": len(rows), "entities": len(eligible)}
    if actual != expected:
        raise ValueError("Incomplete identifier graph")
    receipt = {
        "revision": revision,
        "corpus_snapshot_sha256": snapshot,
        "counts": actual,
        "distinct_source_records": len({r[1] for r in rows}),
        "canonical_source_messages": len({r[3] for r in rows}),
        "candidate_semantics": "co-mention only; no outcome inference",
        "status": "ok",
    }
    with args.output.open("x") as out:
        out.write(json.dumps(receipt, indent=2) + "\n")
    args.output.chmod(0o600)
    db.close()
    print(json.dumps(receipt))


def neighbors(driver, revision, seed_ids, cutoff, limit):
    return execute(
        driver,
        """MATCH(seed:Record)-[first:MENTIONS]->(e:RecallEntity {revision:$revision})
      WHERE seed.id IN $seeds AND seed.event_at<=$cutoff AND first.known_at<=$cutoff
      WITH e,collect(DISTINCT seed.session_id) AS seed_sessions
      MATCH(past:Record)-[seen:MENTIONS]->(e)
      WHERE past.event_at<=$cutoff AND seen.known_at<=$cutoff AND past.inherited=0
      WITH e,seed_sessions,count(DISTINCT seen.canonical_key) AS degree
      WHERE degree>=2 AND degree<=250
      MATCH(r:Record)-[mention:MENTIONS]->(e)
      WHERE r.event_at<=$cutoff AND mention.known_at<=$cutoff AND r.inherited=0
        AND NOT r.id IN $seeds AND NOT r.session_id IN seed_sessions
      WITH r,mention.canonical_key AS canonical_key,sum(1.0/degree) AS score,collect(DISTINCT e.identifier) AS identifiers
      ORDER BY score DESC,r.event_at DESC,r.id
      WITH canonical_key,collect({record:properties(r),score:score,identifiers:identifiers})[0] AS selected
      RETURN selected.record AS record,selected.score AS score,selected.identifiers AS identifiers
      ORDER BY score DESC,record.event_at DESC,record.id LIMIT $limit""",
        revision=revision,
        seeds=seed_ids,
        cutoff=cutoff,
        limit=limit,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--env-file", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    build(p.parse_args())
