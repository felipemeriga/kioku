"""Explicitly run adversarial temporal invariants against the real local Neo4j.

These synthetic fixtures verify engine/query behavior; they are never included in
the real-corpus answer-accuracy denominator. No CI or production service is used.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import uuid
from pathlib import Path

from corpus import SCHEMA, timestamp
from facts import import_bundle
from graph import connect, execute, initialize
from recall import graph_facts


def run(env_file):
    prefix = "contract-" + uuid.uuid4().hex
    revision = None
    checks = []
    with tempfile.TemporaryDirectory(prefix="graph-contract-") as directory:
        root = Path(directory)
        db_path = root / "fixture.sqlite"
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        db.execute(
            "INSERT INTO metadata VALUES('snapshot_sha256',?)", (json.dumps(prefix),)
        )
        specs = [
            ("a", "2026-11-01T12:00:00Z", "attempted", "staging", "fixture"),
            ("d", "2026-11-02T12:00:00Z", "observed", "staging", "fixture"),
            ("b", "2026-11-05T12:00:00Z", "reverted", "staging", "fixture"),
            ("c", "2026-11-10T12:00:00Z", "attempted", "production", "fixture"),
            ("e", "2026-10-31T12:00:00Z", "proposed", "staging", "other"),
        ]
        records = []
        claims = []
        for key, at, status, environment, concept in specs:
            rid = prefix + ":" + key
            quote = "Synthetic contract source for " + key + " says " + status + "."
            row = {
                "id": rid,
                "event_at": timestamp(at),
                "role": "assistant",
                "event_type": "message",
                "inherited": 0,
                "text": quote,
                "source_sha256": "fixture",
                "byte_offset": 0,
                "byte_length": len(quote),
            }
            records.append(row)
            db.execute(
                "INSERT INTO records(id,event_at,role,event_type,inherited,displayable,text,source_sha256,byte_offset,byte_length) VALUES(?,?,?,?,?,1,?,?,?,?)",
                (
                    rid,
                    row["event_at"],
                    row["role"],
                    row["event_type"],
                    0,
                    quote,
                    "fixture",
                    0,
                    len(quote),
                ),
            )
            claims.append(
                {
                    "id": key,
                    "concepts": [concept],
                    "status": status,
                    "authority": "assistant_report",
                    "text": quote,
                    "environment": environment,
                    "mode": "cloud" if key == "c" else "on_prem",
                    "review_note": "Synthetic temporal fixture only.",
                    "supports": [{"record_id": rid, "quote": quote}],
                }
            )
        claims[2]["valid_at"] = "2026-11-01T12:00:00Z"

        def relation(start, end, kind, proof):
            claim = next(c for c in claims if c["id"] == proof)
            return {
                "from": start,
                "to": end,
                "type": kind,
                "support": claim["supports"][0],
                "review_note": "Synthetic temporal fixture only.",
            }

        bundle = {
            "corpus_snapshot_sha256": prefix,
            "concepts": [
                {"id": "fixture", "name": "fixture", "aliases": ["fixture"]},
                {"id": "other", "name": "unrelated", "aliases": ["unrelated"]},
            ],
            "claims": claims,
            "relations": [
                relation("b", "a", "SUPERSEDES", "b"),
                relation("b", "d", "EXPLAINS", "b"),
                relation("c", "b", "RETESTS", "c"),
            ],
        }
        bundle_path = root / "facts.json"
        bundle_path.write_text(json.dumps(bundle))
        db.commit()
        with connect(env_file) as driver:
            initialize(driver)
            try:
                execute(
                    driver,
                    "UNWIND $rows AS row CREATE (r:Record) SET r += row,r.contract_fixture=$prefix",
                    rows=records,
                    prefix=prefix,
                )
                first = import_bundle(bundle_path, db_path, env_file)
                revision = first["revision"]
                before = execute(
                    driver,
                    "MATCH (c:Claim {revision:$revision}) OPTIONAL MATCH (c)-[e]->() RETURN count(DISTINCT c) AS claims,count(e) AS edges",
                    revision=revision,
                )
                import_bundle(bundle_path, db_path, env_file)
                after = execute(
                    driver,
                    "MATCH (c:Claim {revision:$revision}) OPTIONAL MATCH (c)-[e]->() RETURN count(DISTINCT c) AS claims,count(e) AS edges",
                    revision=revision,
                )
                assert before == after
                checks.append("repeat_import_idempotent")

                def recall(at, environment=None, mode=None):
                    result = graph_facts(
                        driver,
                        db,
                        revision,
                        "fixture",
                        timestamp(at),
                        8,
                        environment,
                        mode,
                    )
                    identities = [c["id"] for c in result["claims"]]
                    assert len(identities) == len(set(identities)), (
                        "Duplicate graph result consumed the result budget"
                    )
                    return {c["key"] for c in result["claims"]}

                assert recall("2026-11-03T12:00:00Z") == {"a", "d"}
                checks.append("historical_cutoff")
                assert recall("2026-11-05T11:59:59.999999Z") == {"a", "d"}
                checks.append("one_microsecond_before")
                assert recall("2026-11-05T12:00:00Z") == {"a", "b", "d"}
                checks.append("exact_boundary_inclusive")
                assert recall("2026-11-06T12:00:00Z", "production") == set()
                checks.append("environment_not_inherited")
                assert recall("2026-11-11T12:00:00Z", "production") == {"c"}
                checks.append("cross_environment_edge_blocked")
                assert recall("2026-11-11T12:00:00Z", "production", "on_prem") == set()
                assert recall("2026-11-11T12:00:00Z", "production", "cloud") == {"c"}
                checks.append("mode_is_distinct_from_environment")
                # Deliberately backdate an edge while its cited original remains
                # in the future. Filtering edge properties alone is insufficient.
                execute(
                    driver,
                    "MATCH (a:Claim {id:$a}),(e:Claim {id:$e}) CREATE (a)-[:EXPLAINS {known_at:$known,record_id:$proof}]->(e)",
                    a=revision + ":a",
                    e=revision + ":e",
                    known=timestamp("2026-11-02T12:00:00Z"),
                    proof=prefix + ":b",
                )
                assert "e" not in recall("2026-11-03T12:00:00Z")
                checks.append("future_edge_original_blocked")
                execute(
                    driver,
                    "MATCH (a:Claim {id:$a})-[e:EXPLAINS]->(b:Claim {id:$b}) DELETE e",
                    a=revision + ":a",
                    b=revision + ":e",
                )
                # A corrupt/backdated node must not expose its future support.
                execute(
                    driver,
                    "MATCH (c:Claim {id:$c}) SET c.known_at=$known,c.valid_at=$known WITH c MATCH (c)-[e:RETESTS]->() SET e.known_at=$known,e.record_id=$proof",
                    c=revision + ":c",
                    known=timestamp("2026-11-01T12:00:00Z"),
                    proof=prefix + ":b",
                )
                assert "c" not in recall("2026-11-06T12:00:00Z")
                checks.append("future_leaf_original_blocked")
                execute(
                    driver,
                    "MATCH (c:Claim {id:$c}),(e:Claim {id:$e}) CREATE (c)-[:EXPLAINS {known_at:$known,record_id:$proof}]->(e)",
                    c=revision + ":c",
                    e=revision + ":e",
                    known=timestamp("2026-11-01T12:00:00Z"),
                    proof=prefix + ":b",
                )
                assert "e" not in recall("2026-11-06T12:00:00Z")
                checks.append("future_intermediate_original_blocked")
                assert recall("2026-11-06T12:00:00Z", "unknown") == set()
                checks.append("unknown_environment_abstains")
            finally:
                if revision:
                    execute(
                        driver,
                        "MATCH (n) WHERE (n:Claim OR n:Concept) AND n.revision=$revision DETACH DELETE n",
                        revision=revision,
                    )
                execute(
                    driver,
                    "MATCH (r:Record {contract_fixture:$prefix}) DETACH DELETE r",
                    prefix=prefix,
                )
        db.close()
    return {"status": "ok", "checks": checks, "synthetic_engine_contract_only": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.env_file)))
