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
RELATION_PATTERN = "SUPERSEDES|RETESTS|CONTRADICTS|EXPLAINS|RESOLVES"


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
            [query, cutoff, *sessions, limit],
        )
    ]
    return {
        "hints": hints[:3],
        "records": records,
        "baseline_note": "Frozen-corpus journal lexical discovery and scoped original lexical search; no live Voyage reranker.",
    }


def concept_seeds(db, revision, question):
    words = set(terms(question))
    lower = question.lower()
    scored = []
    for row in db.execute(
        "SELECT id,payload FROM concepts WHERE revision=?", (revision,)
    ):
        concept = json.loads(row["payload"])
        aliases = [concept["name"], *concept["aliases"]]
        score = 0
        for alias in aliases:
            tokens = set(terms(alias))
            score = max(
                score,
                (4 + len(tokens)) if alias.lower() in lower else len(tokens & words),
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


def flat_facts(db, revision, question, cutoff, limit, environment=None):
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
    return {"concepts": concepts, "claims": output}


def graph_facts(driver, db, revision, question, cutoff, limit, environment=None):
    # Identical concept resolver, extracted facts, and final result budget. Start
    # from two recent facts, then use explicit reviewed relationships to recover
    # earlier attempts. This policy is evaluated, not assumed to improve recall.
    flat = flat_facts(db, revision, question, cutoff, limit, environment)
    seeds = [claim["id"] for claim in flat["claims"][:2]]
    query = f"""
    MATCH (seed:Claim) WHERE seed.id IN $seeds AND seed.revision=$revision
    MATCH path=(seed)-[:{RELATION_PATTERN}*0..3]-(c:Claim)
    WHERE all(n IN nodes(path) WHERE n.revision=$revision AND n.known_at<=$cutoff
              AND n.valid_at<=$cutoff AND ($environment IS NULL OR n.environment=$environment))
      AND all(e IN relationships(path) WHERE e.known_at<=$cutoff AND EXISTS {{
        MATCH (proof:Record {{id:e.record_id}}) WHERE proof.event_at<=$cutoff AND proof.inherited=0
      }})
    WITH c,min(length(path)) AS distance
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
        revision=revision,
        cutoff=cutoff,
        limit=limit,
        environment=environment,
    )
    return {
        "concepts": flat["concepts"],
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
                                )
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
