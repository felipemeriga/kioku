"""Validate evidence-backed claims before importing the same facts into two stores.

Exact source quotation validation is mechanical. Whether a quotation warrants a
claim or a semantic relationship still requires a separately recorded review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from corpus import timestamp
from graph import connect, execute

RELATIONS = frozenset(
    {"SUPERSEDES", "RETESTS", "CONTRADICTS", "EXPLAINS", "RESOLVES", "EXTENDS"}
)
AUTHORITIES = frozenset(
    {
        "user_request",
        "user_report",
        "user_correction",
        "assistant_report",
        "tool_observation",
    }
)
STATUSES = frozenset(
    {
        "proposed",
        "attempted",
        "observed",
        "merged",
        "deployed",
        "reverted",
        "unresolved",
        "documented",
    }
)


def validate(bundle, db):
    source_manifest = db.execute(
        "SELECT value FROM metadata WHERE key='snapshot_sha256'"
    ).fetchone()
    if not source_manifest or json.loads(source_manifest[0]) != bundle.get(
        "corpus_snapshot_sha256"
    ):
        raise ValueError("Extraction is not pinned to this frozen corpus")
    if not bundle.get("claims") or not bundle.get("concepts"):
        raise ValueError("No claims or concepts")
    canonical = json.dumps(
        {"normalization_schema": 5, "bundle": bundle},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    revision = hashlib.sha256(canonical).hexdigest()
    concepts = {row["id"] for row in bundle["concepts"]}
    claims = {row["id"]: row for row in bundle["claims"]}
    if len(claims) != len(bundle["claims"]) or len(concepts) != len(bundle["concepts"]):
        raise ValueError("Duplicate identities")
    supports = []
    normalized = []

    def source(reference):
        row = db.execute(
            "SELECT * FROM records WHERE id=?", (reference["record_id"],)
        ).fetchone()
        if not row or row["inherited"] or not row["displayable"] or not row["event_at"]:
            raise ValueError("Source absent, inherited, nondisplayable, or untimed")
        if row["role"] == "assistant" and row["channel"] == "analysis":
            raise ValueError("Private analysis is not a reported or observed outcome")
        quote = reference["quote"]
        if len(quote.strip()) < 12 or quote not in row["text"]:
            raise ValueError("Unsupported source quotation")
        return row

    for key, claim in claims.items():
        if claim["status"] not in STATUSES or claim["authority"] not in AUTHORITIES:
            raise ValueError("Unknown status or authority")
        if not claim.get("concepts") or not set(claim["concepts"]) <= concepts:
            raise ValueError("Unknown or absent concepts")
        if not claim.get("supports") or not claim.get("review_note"):
            raise ValueError("Missing evidence or review note")
        sources = []
        for reference in claim["supports"]:
            row = source(reference)
            sources.append(row)
            supports.append(
                {"claim_key": key, **reference, "source_sha256": row["source_sha256"]}
            )
        roles = {row["role"] for row in sources}
        if (
            claim["authority"] in {"user_request", "user_report", "user_correction"}
            and "user" not in roles
        ):
            raise ValueError("User request has no user original")
        if claim["authority"] == "assistant_report" and "assistant" not in roles:
            raise ValueError("Assistant report has no assistant original")
        if claim["authority"] == "tool_observation" and not any(
            row["event_type"] == "tool_result" for row in sources
        ):
            raise ValueError("Tool observation has no command result")
        commands = []
        if claim["authority"] == "tool_observation":
            if claim.get("observation_kind") not in {
                "command_result",
                "artifact_inspection",
            }:
                raise ValueError("Tool observation needs a reviewed observation kind")
            for reference, row in zip(claim["supports"], sources, strict=True):
                if row["event_type"] != "tool_result":
                    continue
                command = db.execute(
                    "SELECT * FROM records WHERE id=?",
                    (reference.get("command_record_id"),),
                ).fetchone()
                if (
                    not command
                    or command["event_type"] != "tool_call"
                    or not row["call_id"]
                ):
                    raise ValueError("Tool result needs its paired original command")
                if (
                    any(
                        command[field] != row[field]
                        for field in [
                            "session_id",
                            "stream_id",
                            "generation",
                            "call_id",
                        ]
                    )
                    or command["sequence"] >= row["sequence"]
                ):
                    raise ValueError("Command/result provenance mismatch")
                if (
                    not command["event_at"]
                    or command["event_at"] > row["event_at"]
                    or command["inherited"]
                ):
                    raise ValueError(
                        "Command provenance is future, untimed, or inherited"
                    )
                commands.append(command["id"])
        modes = claim.get("modes", [claim.get("mode", "unknown")])
        if (
            not isinstance(modes, list)
            or not modes
            or any(not isinstance(mode, str) or not mode for mode in modes)
        ):
            raise ValueError("Modes must be an explicit nonempty list")
        known = max(row["event_at"] for row in sources)
        valid = timestamp(claim.get("valid_at")) or known
        if target_id := claim.get("valid_at_reference"):
            target = db.execute(
                "SELECT event_at,inherited FROM records WHERE id=?", (target_id,)
            ).fetchone()
            if (
                not target
                or target["inherited"]
                or not target["event_at"]
                or target["event_at"] != valid
            ):
                raise ValueError(
                    "Correction valid time differs from its original target record"
                )
        if valid > known and claim["status"] not in {"proposed", "unresolved"}:
            raise ValueError("A future plan cannot be an established result")
        normalized.append(
            {
                "id": revision + ":" + key,
                "key": key,
                "revision": revision,
                "text": claim["text"],
                "status": claim["status"],
                "authority": claim["authority"],
                "observation_kind": claim.get("observation_kind", "not_applicable"),
                "command_record_ids": commands,
                "known_at": known,
                "valid_at": valid,
                "valid_time_basis": "correction_target_record_time"
                if claim.get("valid_at_reference")
                else "explicit_event_time"
                if claim.get("valid_at")
                else "original_report_time",
                "valid_at_reference": claim.get("valid_at_reference"),
                "current_validity": "not_established_by_archive",
                "concepts": claim["concepts"],
                "environment": claim.get("environment", "unknown"),
                "mode": claim.get("mode", "unknown"),
                "modes": claim.get("modes", [claim.get("mode", "unknown")]),
                "host": claim.get("host", "unknown"),
                "workload": claim.get("workload", "unknown"),
                "version": claim.get("version", "unknown"),
                "review_note": claim["review_note"],
            }
        )
    normalized_by_key = {row["key"]: row for row in normalized}
    relations = []
    for relation in bundle.get("relations", []):
        if (
            relation["type"] not in RELATIONS
            or relation["from"] not in claims
            or relation["to"] not in claims
        ):
            raise ValueError("Invalid semantic edge")
        row = source(relation["support"])
        known = max(
            row["event_at"],
            normalized_by_key[relation["from"]]["known_at"],
            normalized_by_key[relation["to"]]["known_at"],
        )
        if not relation.get("review_note"):
            raise ValueError("Semantic edge needs an explicit review")
        relations.append({**relation, "known_at": known, "revision": revision})
    return revision, normalized, supports, relations


def import_bundle(bundle_path, db_path, env_file):
    bundle = json.loads(bundle_path.read_text())
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    revision, claims, supports, relations = validate(bundle, db)
    db.executescript("""
      CREATE TABLE IF NOT EXISTS claims(revision TEXT,key TEXT,text TEXT,status TEXT,
        authority TEXT,known_at TEXT,valid_at TEXT,environment TEXT,payload TEXT,
        PRIMARY KEY(revision,key));
      CREATE TABLE IF NOT EXISTS claim_support(revision TEXT,claim_key TEXT,record_id TEXT,
        quote TEXT,PRIMARY KEY(revision,claim_key,record_id,quote));
      CREATE TABLE IF NOT EXISTS claim_relations(revision TEXT,from_key TEXT,to_key TEXT,
        type TEXT,known_at TEXT,payload TEXT,PRIMARY KEY(revision,from_key,to_key,type));
      CREATE TABLE IF NOT EXISTS concepts(revision TEXT,id TEXT,payload TEXT,PRIMARY KEY(revision,id));
    """)
    # Immutable revision namespace makes repeat imports idempotent; a changed
    # extraction cannot silently leave old semantic edges active in its revision.
    with db:
        db.executemany(
            "INSERT OR REPLACE INTO claims VALUES(?,?,?,?,?,?,?,?,?)",
            [
                (
                    revision,
                    c["key"],
                    c["text"],
                    c["status"],
                    c["authority"],
                    c["known_at"],
                    c["valid_at"],
                    c["environment"],
                    json.dumps(c),
                )
                for c in claims
            ],
        )
        db.executemany(
            "INSERT OR REPLACE INTO claim_support VALUES(?,?,?,?)",
            [(revision, s["claim_key"], s["record_id"], s["quote"]) for s in supports],
        )
        db.executemany(
            "INSERT OR REPLACE INTO claim_relations VALUES(?,?,?,?,?,?)",
            [
                (revision, r["from"], r["to"], r["type"], r["known_at"], json.dumps(r))
                for r in relations
            ],
        )
        db.executemany(
            "INSERT OR REPLACE INTO concepts VALUES(?,?,?)",
            [(revision, c["id"], json.dumps(c)) for c in bundle["concepts"]],
        )
    with connect(env_file) as driver:
        execute(
            driver,
            "UNWIND $rows AS row MERGE (c:Concept {id:$revision+':'+row.id}) SET c.name=row.name,c.aliases=row.aliases,c.revision=$revision",
            rows=bundle["concepts"],
            revision=revision,
        )
        execute(
            driver,
            "UNWIND $rows AS row MERGE (c:Claim {id:row.id}) SET c += row WITH c,row UNWIND row.concepts AS concept MATCH (t:Concept {id:$revision+':'+concept}) MERGE (c)-[:ABOUT]->(t)",
            rows=claims,
            revision=revision,
        )
        execute(
            driver,
            "UNWIND $rows AS row MATCH (c:Claim {id:$revision+':'+row.claim_key}),(r:Record {id:row.record_id}) MERGE (c)-[s:SUPPORTED_BY {quote:row.quote}]->(r) SET s.source_sha256=row.source_sha256",
            rows=supports,
            revision=revision,
        )
        for kind in sorted(RELATIONS):
            selected = [r for r in relations if r["type"] == kind]
            execute(
                driver,
                f"UNWIND $rows AS row MATCH (a:Claim {{id:$revision+':'+row.from}}),(b:Claim {{id:$revision+':'+row.to}}),(r:Record {{id:row.support.record_id}}) MERGE (a)-[e:{kind}]->(b) SET e.known_at=row.known_at,e.record_id=row.support.record_id,e.quote=row.support.quote,e.review_note=row.review_note",
                rows=selected,
                revision=revision,
            )
    db.close()
    return {
        "revision": revision,
        "claims": len(claims),
        "supports": len(supports),
        "relations": len(relations),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(import_bundle(args.bundle, args.corpus, args.env_file)))
