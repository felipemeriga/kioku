"""Diagnostic reviewed-source coverage. This is neither blind nor answer accuracy.

Gold is consumed after retrieval, never by recall.py. A lexical original match
counts only when the reviewed exact quote is visible at the same source time.
This is a coverage proxy: an included quote does not prove model understanding.
"""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def run(args):
    gold = json.loads(args.gold.read_text())
    db = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    support = {}
    for row in db.execute(
        "SELECT s.claim_key,s.quote,r.event_at FROM claim_support s JOIN records r ON r.id=s.record_id WHERE s.revision=?",
        (gold["facts_revision"],),
    ):
        support.setdefault(row["claim_key"], []).append(dict(row))
    receipts = [json.loads(line) for line in args.replay.read_text().splitlines()]
    if not receipts or receipts[-1].get("type") != "complete":
        raise ValueError("Replay is incomplete; do not silently drop unfinished trials")
    terminal = receipts[-1]
    if terminal.get("revision", gold["facts_revision"]) != gold["facts_revision"]:
        raise ValueError("Gold and retrieved fact revisions differ")
    if (
        gold.get("questions_sha256")
        and terminal.get("questions_sha256") != gold["questions_sha256"]
    ):
        raise ValueError("Gold and replay question manifests differ")
    scores = []
    seen = set()
    for trial in receipts:
        if trial.get("case_id"):
            identity = (trial["case_id"], trial["method"], trial["trial"])
            if identity in seen:
                raise ValueError("Duplicate trial receipt")
            seen.add(identity)
        case = trial.get("case_id")
        if case not in gold["positive_cases"]:
            continue
        result = trial.get("result", {})
        retrieved = {c["key"] for c in result.get("claims", [])}
        if trial["method"] in {"journal_first", "entity_sqlite", "entity_graph"}:
            retrieved = {
                key
                for key, sources in support.items()
                if any(
                    s["quote"] in r.get("text", "")
                    and s["event_at"] == r.get("event_at")
                    for s in sources
                    for r in result.get("records", [])
                )
            }
        groups = gold["positive_cases"][case]
        missing = [g for g in groups if not set(g) & retrieved]
        scores.append(
            {
                "case_id": case,
                "method": trial["method"],
                "trial": trial["trial"],
                "items": len(groups),
                "covered": len(groups) - len(missing),
                "missing": missing,
                "retrieval_error": trial.get("status") != "ok",
            }
        )
    if not scores:
        raise ValueError("No positive trials to score")
    for method, trial_number in {(s["method"], s["trial"]) for s in scores}:
        present = {
            s["case_id"]
            for s in scores
            if s["method"] == method and s["trial"] == trial_number
        }
        if present != set(gold["positive_cases"]):
            raise ValueError(
                "Positive cases are missing from a method/trial denominator"
            )
    totals = {}
    for method in sorted({s["method"] for s in scores}):
        selected = [s for s in scores if s["method"] == method]
        total = sum(s["items"] for s in selected)
        covered = sum(s["covered"] for s in selected)
        totals[method] = {
            "covered": covered,
            "items": total,
            "coverage": covered / total,
            "fully_covered_questions": sum(not s["missing"] for s in selected),
            "questions": len(selected),
            "retrieval_errors": sum(s["retrieval_error"] for s in selected),
        }
    report = {
        "description": __doc__,
        "gold_sha256": hashlib.sha256(args.gold.read_bytes()).hexdigest(),
        "replay_sha256": hashlib.sha256(args.replay.read_bytes()).hexdigest(),
        "not_blind": True,
        "not_answer_accuracy": True,
        "totals": totals,
        "scores": scores,
        "excluded_from_positive_coverage": {
            "journal_only": gold["journal_only_cases"],
            "unsupported": gold["unsupported_cases"],
        },
    }
    with args.output.open("x") as f:
        f.write(json.dumps(report, indent=2) + "\n")
    args.output.chmod(0o600)
    db.close()
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["gold", "replay", "corpus", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    run(p.parse_args())
