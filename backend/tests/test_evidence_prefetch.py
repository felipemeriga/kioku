"""Source selection and coverage must not leak or invent historical context."""

import json
from datetime import datetime, timezone

import pytest

from services.evidence_prefetch import date_filters, history_question, prefetch

NOW = datetime(2026, 11, 9, 2, tzinfo=timezone.utc)  # Still Sunday in São Paulo.


@pytest.mark.parametrize(
    "question,expected",
    [
        ("What did we work on this week?", True),
        ("Have we tried the smaller budget?", True),
        ("What did the documentation say about memory?", False),
        ("Where is ChargeService defined?", False),
        ("How does the ingestion pipeline work?", False),
        ("When later sessions discussed the October incident, was its cause proven?", True),
    ],
)
def test_source_intent(question, expected):
    assert history_question(question) is expected


@pytest.mark.parametrize(
    "question,expected",
    [
        (
            "What did we work on this week?",
            {"from_date": "2026-11-02", "through_date": "2026-11-08"},
        ),
        (
            "What issues did we have yesterday?",
            {"from_date": "2026-11-07", "through_date": "2026-11-07"},
        ),
        ("Work from November 2–6, 2026", {"from_date": "2026-11-02", "through_date": "2026-11-06"}),
        ("What did we know by the end of November 5, 2026?", {"as_of": "2026-11-05"}),
        ("What did we try before November 5, 2026?", {"as_of": "2026-11-04"}),
        (
            "Work from 2026-10-31 through 2026-11-02",
            {"from_date": "2026-10-31", "through_date": "2026-11-02"},
        ),
        (
            "What did we work on last month?",
            {"from_date": "2026-10-01", "through_date": "2026-10-31"},
        ),
        (
            "What did we work on in November 2026?",
            {"from_date": "2026-11-01", "through_date": "2026-11-08"},
        ),
        ("When later sessions discussed the October incident, was its cause proven?", {}),
        ("What is our latest setting, not whether it is deployed today?", {}),
        ("Recorded on November 31, 2026", {}),
    ],
)
def test_time_is_local_and_incident_mentions_do_not_become_record_filters(question, expected):
    assert date_filters(question, "America/Sao_Paulo", NOW) == expected


def test_document_scope_cannot_expand_into_history():
    calls = []

    def execute(name, args):
        calls.append(name)
        return "Document evidence [1]"

    evidence, _ = prefetch("What did we try?", "UTC", execute, filename="only-this.pdf")
    assert calls == ["knowledge_base_search"]
    assert evidence == "Document evidence [1]"


def test_history_is_prefetched_with_expansion_and_only_an_authorized_named_folder():
    calls = []

    def execute(name, args):
        calls.append((name, args))
        return json.dumps(
            {"matches": [{"reference": "signed-cutoff"}]}
            if name == "search_agent_history"
            else {"evidence": [{"excerpt": "original [1]"}]}
        )

    evidence, _ = prefetch(
        "In payments-repo, what did we try on November 5, 2026?",
        "UTC",
        execute,
        folders=[{"id": "owned", "name": "payments-repo"}],
    )
    assert calls[0][0] == "search_agent_history"
    assert calls[0][1]["folder"] == "owned"
    assert calls[0][1]["from_date"] == "2026-11-05"
    assert "payments-repo" not in calls[0][1]["query"]
    assert calls[1] == (
        "read_agent_evidence",
        {"reference": "signed-cutoff", "before_records": 1, "after_records": 1, "char_limit": 4000},
    )
    assert "original [1]" in evidence


def test_overview_prefetch_pages_days_and_retains_remaining_coverage():
    calls = []

    def execute(name, args):
        calls.append(args)
        return json.dumps(
            {
                "matches": [],
                "activity": {
                    "days": [{"date": str(len(calls))}],
                    "next_offset": len(calls) * 10,
                    "has_more": True,
                },
            }
        )

    evidence, _ = prefetch("What did we work on this week?", "UTC", execute)
    pages = json.loads(evidence)["pages"]
    assert len(calls) == len(pages) == 5
    assert calls[-1]["offset"] == 40
    assert pages[-1]["activity"]["has_more"] is True


def test_no_tools_request_does_not_silently_retrieve_documents():
    def execute(*_):
        raise AssertionError("Unexpected retrieval")

    evidence, calls = prefetch("Reply with exactly OK; do not use tools.", "UTC", execute)
    assert not calls
    assert json.loads(evidence)["source"] == "none"


def test_invalid_history_result_is_not_replaced_by_unrelated_documents():
    evidence, calls = prefetch("What did we try?", "UTC", lambda *_: "upstream unavailable")
    assert len(calls) == 1 and calls[0]["name"] == "search_agent_history"
    assert json.loads(evidence)["pages"][0]["code"] == "invalid_history_result"
