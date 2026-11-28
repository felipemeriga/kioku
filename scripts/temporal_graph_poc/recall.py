"""Manual recall comparison. This process never opens answer annotations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from corpus import timestamp
from graph import connect, execute

STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "before",
        "by",
        "can",
        "did",
        "do",
        "does",
        "ever",
        "for",
        "from",
        "had",
        "has",
        "have",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "its",
        "latest",
        "most",
        "not",
        "of",
        "on",
        "only",
        "or",
        "our",
        "previously",
        "that",
        "the",
        "their",
        "there",
        "these",
        "this",
        "to",
        "tried",
        "try",
        "us",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "would",
        "yet",
        "actually",
        "about",
        "something",
        "similar",
        "recorded",
        "work",
        "state",
        "evidence",
        "established",
        "verified",
        "changed",
        "change",
        "earlier",
        "later",
        "current",
        "through",
        "then",
        "also",
        "versus",
        "rather",
        "than",
        "already",
        "still",
        "each",
        "between",
        "after",
    ]
)
RELATION_PATTERN = "SUPERSEDES|RETESTS|CONTRADICTS|EXPLAINS|RESOLVES|EXTENDS"


def terms(question):
    return list(
        dict.fromkeys(
            word
            for word in re.findall(r"[\w]+", question.lower())
            if len(word) > 2 and word not in STOP
        )
    )[:32]


def fts_query(question):
    return " OR ".join('"' + word.replace('"', '""') + '"' for word in terms(question))


def journal_hints(db, question, cutoff):
    query = fts_query(question)
    if not query:
        return []
    return [
        dict(row)
        for row in db.execute(
            """SELECT j.id,j.session_id,j.captured_at,j.title,j.body,bm25(journal_fts) AS score
      FROM journal_fts JOIN journals j ON j.id=journal_fts.id
      WHERE journal_fts MATCH ? AND j.captured_at<=? ORDER BY score,j.captured_at DESC LIMIT 3""",
            (query, cutoff),
        )
    ]


def annotate_coverage(db, result, cutoff):
    missing = db.execute(
        """SELECT count(DISTINCT j.session_id) FROM journals j WHERE j.captured_at<=?
      AND NOT EXISTS(SELECT 1 FROM sessions s JOIN records r ON r.session_id=s.id
        WHERE s.native_id=j.session_id AND r.displayable=1 AND r.event_at<=?)""",
        (cutoff, cutoff),
    ).fetchone()[0]
    result["coverage"] = {
        "complete": False,
        "journal_sessions_without_timed_originals": missing,
        "absence_proves_never": False,
        "current_state_verified": False,
        "historical_journal_revision_verified": False,
    }
    for hint in result.get("hints", []):
        hint["source_kind"] = "revisable_journal_discovery_hint"
        hint["original_verified"] = False
    result["answerability"] = (
        "original_evidence_candidates"
        if result.get("records") or result.get("claims")
        else "journal_hint_only"
        if result.get("hints")
        else "not_established"
    )
    return result


def journal_first(db, question, cutoff, limit):
    query = fts_query(question)
    if not query:
        return {"hints": [], "records": []}
    hints = [
        dict(row)
        for row in db.execute(
            """
        SELECT j.id,j.session_id,j.captured_at,j.title,j.body,bm25(journal_fts) AS score
        FROM journal_fts JOIN journals j ON j.id=journal_fts.id
        WHERE journal_fts MATCH ? AND j.captured_at<=?
        ORDER BY score,j.captured_at DESC LIMIT 30
    """,
            (query, cutoff),
        )
    ]
    selected = list(dict.fromkeys(row["session_id"] for row in hints))[:3]
    sessions = [
        row[0]
        for native in selected
        for row in db.execute("SELECT id FROM sessions WHERE native_id=?", (native,))
    ]
    if not sessions:
        return {"hints": hints[:3], "records": []}
    placeholders = ",".join("?" for _ in sessions)
    records = [
        dict(row)
        for row in db.execute(
            f"""
        SELECT r.id,r.session_id,r.event_at,r.role,r.event_type,r.source_sha256,
          r.byte_offset,r.byte_length,substr(r.text,1,12000) AS text,bm25(record_fts) AS score
        FROM record_fts JOIN records r ON r.id=record_fts.id
        WHERE record_fts MATCH ? AND r.event_at<=? AND r.inherited=0
          AND r.session_id IN ({placeholders}) ORDER BY score LIMIT ?
    """,
            [query, cutoff, *sessions, limit * 20],
        )
    ]
    unique = []
    seen = set()
    for row in records:
        identity = (
            row["session_id"],
            row["role"],
            row["event_type"],
            row["event_at"][:19],
            row["text"],
        )
        if identity not in seen:
            unique.append(row)
            seen.add(identity)
        if len(unique) == limit:
            break
    return {
        "hints": hints[:3],
        "records": unique,
        "baseline_note": "Frozen-corpus journal lexical discovery and scoped original lexical search; no live Voyage reranker.",
    }


def concept_seeds(db, revision, question):
    words = set(terms(question))
    normalized_question = " " + " ".join(re.findall(r"\w+", question.casefold())) + " "
    scored = []
    for row in db.execute(
        "SELECT id,payload FROM concepts WHERE revision=?", (revision,)
    ):
        concept = json.loads(row["payload"])
        aliases = [concept["name"], *concept["aliases"]]
        score = 0
        for alias in aliases:
            tokens = set(terms(alias))
            normalized_alias = (
                " " + " ".join(re.findall(r"\w+", alias.casefold())) + " "
            )
            score = max(
                score,
                (4 + len(tokens))
                if normalized_alias.strip() and normalized_alias in normalized_question
                else len(tokens & words),
            )
        if score:
            scored.append((row["id"], score))
    if not scored:
        return []
    highest = max(score for _, score in scored)
    return [
        key
        for key, score in sorted(scored, key=lambda p: (-p[1], p[0]))
        if score >= max(2, highest / 2)
    ][:3]


def flat_facts(db, revision, question, cutoff, limit, environment=None, mode=None):
    concepts = concept_seeds(db, revision, question)
    output = []
    for row in db.execute(
        "SELECT payload FROM claims WHERE revision=? AND known_at<=? AND valid_at<=? ORDER BY known_at DESC,key",
        (revision, cutoff, cutoff),
    ):
        claim = json.loads(row["payload"])
        if not set(claim["concepts"]) & set(concepts):
            continue
        if environment and claim["environment"] != environment:
            continue
        if mode and mode not in claim.get("modes", [claim.get("mode", "unknown")]):
            continue
        supports = [
            dict(s)
            for s in db.execute(
                """SELECT s.record_id,s.quote,r.event_at,r.role,r.event_type,r.source_sha256,r.byte_offset,r.byte_length
          FROM claim_support s JOIN records r ON r.id=s.record_id
          WHERE s.revision=? AND s.claim_key=? AND r.event_at<=? AND r.inherited=0""",
                (revision, claim["key"], cutoff),
            )
        ]
        if supports:
            output.append({**claim, "supports": supports})
        if len(output) >= limit:
            break
    keys = {claim["key"] for claim in output}
    relations = []
    for row in db.execute(
        "SELECT payload FROM claim_relations WHERE revision=? AND known_at<=?",
        (revision, cutoff),
    ):
        relation = json.loads(row["payload"])
        proof = db.execute(
            "SELECT event_at,inherited FROM records WHERE id=?",
            (relation["support"]["record_id"],),
        ).fetchone()
        if (
            relation["from"] in keys
            and relation["to"] in keys
            and proof
            and proof["event_at"]
            and proof["event_at"] <= cutoff
            and not proof["inherited"]
        ):
            relations.append(relation)
    return {
        "concepts": concepts,
        "claims": output,
        "relations": relations,
        "hints": journal_hints(db, question, cutoff) if not output else [],
    }


def safe_claim(variable):
    """Require original support on every traversed node, not only on leaves."""
    return f"""{variable}.revision=$revision AND {variable}.known_at<=$cutoff
      AND {variable}.valid_at<=$cutoff
      AND ($environment IS NULL OR {variable}.environment=$environment)
      AND ($mode IS NULL OR $mode IN {variable}.modes)
      AND EXISTS {{ MATCH ({variable})-[:SUPPORTED_BY]->(proof:Record)
                   WHERE proof.event_at<=$cutoff AND proof.inherited=0 }}
      AND NOT EXISTS {{ MATCH ({variable})-[:SUPPORTED_BY]->(bad:Record)
        WHERE bad.event_at IS NULL OR bad.event_at>$cutoff OR bad.inherited<>0 }}"""


def graph_facts(
    driver, db, revision, question, cutoff, limit, environment=None, mode=None
):
    # Both stores use the same concept resolver and extracted facts. Neo4j chooses
    # its own seeds and performs actual semantic and co-topic traversal. Co-topic
    # edges are discovery only: they do not assert causality or supersession.
    concepts = concept_seeds(db, revision, question)
    parameters = {
        "revision": revision,
        "cutoff": cutoff,
        "environment": environment,
        "mode": mode,
    }
    seed_rows = execute(
        driver,
        f"""MATCH (seed:Claim)-[:ABOUT]->(topic:Concept)
      WHERE topic.id IN $topics AND {safe_claim("seed")}
      WITH DISTINCT seed ORDER BY seed.known_at DESC,seed.key LIMIT 2
      RETURN seed.id AS id""",
        topics=[revision + ":" + c for c in concepts],
        **parameters,
    )
    seeds = [row["id"] for row in seed_rows]
    query = f"""
    CALL {{
    MATCH (seed:Claim) WHERE seed.id IN $seeds AND seed.revision=$revision
    MATCH path=(seed)-[:{RELATION_PATTERN}*0..3]-(c:Claim)
    WHERE all(n IN nodes(path) WHERE {safe_claim("n")})
      AND all(e IN relationships(path) WHERE e.known_at<=$cutoff AND EXISTS {{
        MATCH (proof:Record {{id:e.record_id}}) WHERE proof.event_at<=$cutoff AND proof.inherited=0
      }})
    RETURN c,length(path) AS depth
    UNION
    MATCH (seed:Claim)-[:ABOUT]->(:Concept)<-[:ABOUT]-(c:Claim)
    WHERE seed.id IN $seeds AND {safe_claim("seed")} AND {safe_claim("c")}
    RETURN c,4 AS depth
    }}
    WITH c,collect(DISTINCT depth) AS distances
    WITH c,reduce(best=4,depth IN distances | CASE WHEN depth<best THEN depth ELSE best END) AS distance
    ORDER BY distance,c.known_at DESC,c.key
    LIMIT $limit
    MATCH (c)-[support:SUPPORTED_BY]->(r:Record)
    WHERE r.event_at<=$cutoff AND r.inherited=0
    RETURN properties(c) AS claim,distance,
      collect({{record_id:r.id,quote:support.quote,event_at:r.event_at,role:r.role,
        event_type:r.event_type,source_sha256:r.source_sha256,
        byte_offset:r.byte_offset,byte_length:r.byte_length}}) AS supports
    ORDER BY distance,claim.known_at DESC,claim.key
    """
    rows = execute(
        driver,
        query,
        seeds=seeds,
        limit=limit,
        **parameters,
    )
    ids = [row["claim"]["id"] for row in rows]
    relations = execute(
        driver,
        """MATCH (a:Claim)-[edge]->(b:Claim)
      WHERE a.id IN $ids AND b.id IN $ids AND type(edge) IN $types AND edge.known_at<=$cutoff
      MATCH (proof:Record {id:edge.record_id}) WHERE proof.event_at<=$cutoff AND proof.inherited=0
      RETURN a.key AS from,b.key AS to,type(edge) AS type,edge.known_at AS known_at,
        edge.record_id AS record_id,edge.quote AS quote,edge.review_note AS review_note
      ORDER BY from,to,type""",
        ids=ids,
        types=RELATION_PATTERN.split("|"),
        cutoff=cutoff,
    )
    hints = []
    if not rows and (hint_query := fts_query(question)):
        hints = execute(
            driver,
            """CALL db.index.fulltext.queryNodes('journal_text',$text_query) YIELD node,score
          WHERE node.captured_at<=$cutoff
          RETURN node.id AS id,node.native_session_id AS session_id,node.captured_at AS captured_at,
            node.title AS title,node.body AS body,score ORDER BY score DESC,captured_at DESC LIMIT 3""",
            text_query=hint_query,
            cutoff=cutoff,
        )
    return {
        "concepts": concepts,
        "relations": relations,
        "hints": hints,
        "claims": [
            {**row["claim"], "distance": row["distance"], "supports": row["supports"]}
            for row in rows
        ],
    }


def run(args):
    data = args.questions.read_bytes()
    if hashlib.sha256(data).hexdigest() != args.sha256:
        raise ValueError("Question manifest changed")
    manifest = json.loads(data)
    db = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    driver = connect(args.env_file)
    try:
        with os.fdopen(
            os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as out:
            for trial in range(args.repeats):
                for case in manifest["cases"]:
                    cutoff = timestamp(case["as_of"])
                    limit = case.get("limit", 8)
                    for method in ["journal_first", "flat_facts", "graph_facts"]:
                        begin = time.perf_counter()
                        try:
                            if method == "journal_first":
                                result = journal_first(
                                    db, case["question"], cutoff, limit
                                )
                            elif method == "flat_facts":
                                result = flat_facts(
                                    db,
                                    args.revision,
                                    case["question"],
                                    cutoff,
                                    limit,
                                    case.get("environment"),
                                    case.get("mode"),
                                )
                            else:
                                result = graph_facts(
                                    driver,
                                    db,
                                    args.revision,
                                    case["question"],
                                    cutoff,
                                    limit,
                                    case.get("environment"),
                                    case.get("mode"),
                                )
                            result = annotate_coverage(db, result, cutoff)
                            receipt = {
                                "case_id": case["id"],
                                "trial": trial,
                                "method": method,
                                "as_of": cutoff,
                                "status": "ok",
                                "result": result,
                            }
                        except Exception as exc:  # noqa: BLE001 - retain every failed evaluation trial
                            receipt = {
                                "case_id": case["id"],
                                "trial": trial,
                                "method": method,
                                "as_of": cutoff,
                                "status": "error",
                                "error_type": type(exc).__name__,
                            }
                        receipt["latency_ms"] = (time.perf_counter() - begin) * 1000
                        out.write(json.dumps(receipt) + "\n")
                        out.flush()
                        print(
                            json.dumps(
                                {
                                    k: v
                                    for k, v in receipt.items()
                                    if k not in {"result"}
                                }
                            ),
                            flush=True,
                        )
            out.write(
                json.dumps(
                    {
                        "type": "complete",
                        "questions_sha256": args.sha256,
                        "revision": args.revision,
                    }
                )
                + "\n"
            )
    finally:
        driver.close()
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=1)
    run(parser.parse_args())
