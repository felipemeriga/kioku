"""Strict answer accuracy gate: partial, missing, failed or unaudited = not passing.

An audited pass requires a successful nonempty answer and resolving citation
numbers. The audit itself must establish correctness and claim support; this
script does not pretend that citation resolution proves faithfulness.
"""

import argparse
import json
import os
import re
import statistics
from collections import defaultdict
from pathlib import Path


def summarize(cases, results, audits, model, target=0.95):
    ids = [case["id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate manifest cases")
    by_id = {}
    for result in results:
        if result["id"] in by_id:
            raise ValueError("Duplicate results; preserve explicit trial identities")
        by_id[result["id"]] = result
    if set(by_id) - set(ids):
        raise ValueError("Results contain trials outside this manifest")
    groups = defaultdict(list)
    for case in cases:
        result = by_id.get(case["id"], {})
        audit = audits.get(case["id"], {})
        answer = result.get("answer", "")
        cited = set(re.findall(r"\[(\d+)\]", answer))
        retrieval = result.get("retrieval", {})
        available = {str(c["number"]) for c in retrieval.get("citations", [])}
        if "oracle_evidence" in case:
            available |= set(
                re.findall(r"^\[(\d+)\]", case["oracle_evidence"], re.MULTILINE)
            )
        valid = cited <= available and (
            bool(cited) or not case.get("citation_required", True)
        )
        control = (result.get("usage") or {}).get("thinking_control") or {}
        label_verified = (
            result.get("model") == case["model"]
            and result.get("effort") == case.get("effort", "low")
            and control.get("effort") == case.get("effort", "low")
        )
        passed = bool(
            result.get("success")
            and answer.strip()
            and valid
            and label_verified
            and audit.get("verdict") == "pass"
        )
        stage = "oracle" if "oracle_evidence" in case else "retrieval"
        groups[
            (
                case["model"],
                case.get("effort", "low"),
                case["domain"],
                case.get("split", "regression"),
                stage,
            )
        ].append(
            {
                "passed": passed,
                "audited": bool(audit),
                "exported": bool(result),
                "seconds": result.get("total_seconds"),
                "invalid_citations": not valid,
            }
        )
    summaries = []
    for (family, effort, domain, split, stage), rows in sorted(groups.items()):
        times = [r["seconds"] for r in rows if isinstance(r["seconds"], (int, float))]
        summaries.append(
            {
                "model": family,
                "effort": effort,
                "domain": domain,
                "split": split,
                "stage": stage,
                "total": len(rows),
                "passed": sum(r["passed"] for r in rows),
                "accuracy": sum(r["passed"] for r in rows) / len(rows),
                "audited": sum(r["audited"] for r in rows),
                "missing_results": sum(not r["exported"] for r in rows),
                "invalid_citation_cases": sum(r["invalid_citations"] for r in rows),
                "median_seconds": statistics.median(times) if times else None,
            }
        )
    candidate = [
        r
        for r in summaries
        if r["model"] == model and r["effort"] == "low" and r["stage"] == "retrieval"
    ]
    heldout_domains = {r["domain"] for r in candidate if r["split"] == "heldout"}
    gate = heldout_domains >= {"memory", "documents", "code"} and all(
        r["accuracy"] >= target
        and r["audited"] == r["total"]
        and not r["missing_results"]
        for r in candidate
    )
    return {
        "target": target,
        "candidate_model": model,
        "gate_passed": gate,
        "groups": summaries,
        "interpretation": "Curated benchmark accuracy, not a population guarantee. "
        "Audits must verify claims against independent frozen source truth. "
        "Oracle trials diagnose synthesis and never satisfy the retrieval gate.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--audits", type=Path, required=True)
    parser.add_argument("--candidate-model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    results = [
        json.loads(line)
        for line in args.results.read_text().splitlines()
        if line.strip()
    ]
    report = summarize(
        manifest["cases"],
        results,
        json.loads(args.audits.read_text()),
        args.candidate_model,
    )
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(report, stream, indent=2)
    print(
        json.dumps({"gate_passed": report["gate_passed"], "target": report["target"]})
    )
