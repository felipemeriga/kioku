"""Audit the complete reviewed overlay, independently of retrieval ranking.

Byte provenance is not semantic truth. This checks that the database preserves
all reviewed facts, authorities and explicit relationships without extra edges.
"""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from graph import connect, execute
from recall import RELATION_PATTERN


def audit(corpus, env_file, revision):
    db = sqlite3.connect(f"file:{corpus}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    expected = {
        c["id"]: c
        for r in db.execute("SELECT payload FROM claims WHERE revision=?", (revision,))
        for c in [json.loads(r[0])]
    }
    if not expected:
        raise ValueError("No reviewed claims in revision")
    expected_supports = sorted(
        (
            revision + ":" + r["claim_key"],
            r["record_id"],
            r["quote"],
            r["source_sha256"],
        )
        for r in db.execute(
            "SELECT s.*,r.source_sha256 FROM claim_support s JOIN records r ON r.id=s.record_id WHERE s.revision=?",
            (revision,),
        )
    )
    expected_topics = sorted(
        (c["id"], revision + ":" + topic)
        for c in expected.values()
        for topic in c["concepts"]
    )
    expected_edges = sorted(
        (
            revision + ":" + r["from"],
            revision + ":" + r["to"],
            r["type"],
            r["known_at"],
            r["support"]["record_id"],
            r["support"]["quote"],
            r["review_note"],
        )
        for row in db.execute(
            "SELECT payload FROM claim_relations WHERE revision=?", (revision,)
        )
        for r in [json.loads(row[0])]
    )
    with connect(env_file) as driver:
        actual = {
            r["claim"]["id"]: r["claim"]
            for r in execute(
                driver,
                "MATCH(c:Claim {revision:$revision}) RETURN properties(c) AS claim ORDER BY c.id",
                revision=revision,
            )
        }
        supports = sorted(
            (r["claim_id"], r["record_id"], r["quote"], r["source_sha256"])
            for r in execute(
                driver,
                "MATCH(c:Claim {revision:$revision})-[s:SUPPORTED_BY]->(r:Record) RETURN c.id AS claim_id,r.id AS record_id,s.quote AS quote,s.source_sha256 AS source_sha256",
                revision=revision,
            )
        )
        topics = sorted(
            (r["claim_id"], r["topic_id"])
            for r in execute(
                driver,
                "MATCH(c:Claim {revision:$revision})-[:ABOUT]->(t:Concept) RETURN c.id AS claim_id,t.id AS topic_id",
                revision=revision,
            )
        )
        edges = sorted(
            (
                r["from"],
                r["to"],
                r["type"],
                r["known_at"],
                r["record_id"],
                r["quote"],
                r["review_note"],
            )
            for r in execute(
                driver,
                "MATCH(a:Claim {revision:$revision})-[e]->(b:Claim) WHERE type(e) IN $types RETURN a.id AS from,b.id AS to,type(e) AS type,e.known_at AS known_at,e.record_id AS record_id,e.quote AS quote,e.review_note AS review_note",
                revision=revision,
                types=RELATION_PATTERN.split("|"),
            )
        )
    failures = []
    if set(actual) != set(expected):
        failures.append("claim_id_set")
    for key, c in expected.items():
        if any(actual.get(key, {}).get(field) != value for field, value in c.items()):
            failures.append("claim_fields:" + key)
        if c.get("current_validity") != "not_established_by_archive":
            failures.append("unverified_current_state_promoted:" + key)
    if supports != expected_supports:
        failures.append("support_edges")
    if topics != expected_topics:
        failures.append("concept_edges")
    if edges != expected_edges:
        failures.append("semantic_edges")
    content = {
        "claims": actual,
        "supports": supports,
        "topics": topics,
        "semantic_edges": edges,
    }
    result = {
        "revision": revision,
        "claims_checked": len(expected),
        "supports_checked": len(expected_supports),
        "semantic_edges_checked": len(expected_edges),
        "failures": failures,
        "fingerprint": hashlib.sha256(
            json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "status": "failed" if failures else "ok",
        "semantic_truth_independently_proven": False,
    }
    db.close()
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--env-file", type=Path, required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = audit(args.corpus, args.env_file, args.revision)
    with args.output.open("x") as f:
        f.write(json.dumps(result, indent=2) + "\n")
    args.output.chmod(0o600)
    print(json.dumps(result))
    if result["failures"]:
        raise SystemExit(1)
