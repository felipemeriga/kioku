"""An accuracy target cannot be met by dropping hard or missing cases."""

import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[2] / "scripts/benchmarks/grounded_report.py"
spec = importlib.util.spec_from_file_location("grounded_gate", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def cohort():
    cases = [
        {"id": f"{domain}-{i}", "model": "model", "domain": domain, "split": "heldout"}
        for domain in ["memory", "documents", "code"]
        for i in range(20)
    ]
    results = [
        {
            "id": c["id"],
            "model": "model",
            "effort": "low",
            "success": True,
            "answer": "Supported fact [1]",
            "total_seconds": 5,
            "usage": {"thinking_control": {"effort": "low"}},
            "retrieval": {"citations": [{"number": 1}]},
        }
        for c in cases
    ]
    audits = {c["id"]: {"verdict": "pass"} for c in cases}
    return cases, results, audits


def test_partial_answers_count_as_failures_and_weak_domains_are_not_hidden():
    cases, results, audits = cohort()
    audits["memory-0"] = {"verdict": "partial"}
    report = module.summarize(cases, results, audits, "model")
    assert report["gate_passed"]  # Exactly95percent in this domain.
    audits["memory-1"] = {"verdict": "partial"}
    report = module.summarize(cases, results, audits, "model")
    assert not report["gate_passed"]  # Aggregate58/60 would hide90percent memory.
    assert next(r for r in report["groups"] if r["domain"] == "memory")["accuracy"] == 0.9


def test_missing_exports_and_missing_audits_never_shrink_the_denominator():
    cases, results, audits = cohort()
    report = module.summarize(cases, results[2:], audits, "model")
    assert not report["gate_passed"]
    assert sum(r["total"] for r in report["groups"]) == 60
    audits.pop("memory-0")
    audits.pop("memory-1")
    assert not module.summarize(cases, results, audits, "model")["gate_passed"]


def test_wrong_effort_or_invalid_citations_fail_even_with_an_audit_pass():
    cases, results, audits = cohort()
    results[0]["usage"]["thinking_control"]["effort"] = "high"
    results[1]["answer"] = "Invented source [999]"
    assert not module.summarize(cases, results, audits, "model")["gate_passed"]


def test_oracle_diagnostics_do_not_satisfy_the_retrieval_gate():
    cases, results, audits = cohort()
    for case in cases:
        case["oracle_evidence"] = "[1] Verified source"
    assert not module.summarize(cases, results, audits, "model")["gate_passed"]


def test_duplicate_or_unlisted_trials_are_rejected():
    cases, results, audits = cohort()
    with pytest.raises(ValueError):
        module.summarize(cases, results + [results[0]], audits, "model")
    with pytest.raises(ValueError):
        module.summarize(cases, results + [{"id": "unlisted"}], audits, "model")


def test_formal_source_locked_cases_cannot_credit_unverified_snapshot_answers():
    cases, results, audits = cohort()
    for case in cases:
        case["source_lock_required"] = True
    assert not module.summarize(cases, results, audits, "model")["gate_passed"]
    for result in results:
        result["source_verified"] = True
    assert module.summarize(cases, results, audits, "model")["gate_passed"]
