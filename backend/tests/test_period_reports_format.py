"""Chronological reports preserve intent, dated updates, and exact provenance."""

import json
from copy import deepcopy

import jsonschema
import pytest

from services.maintenance.operations import build_request, completion_schema, validate_result
from services.period_reports import render_report, report_quote_choices, validate_report


def fixture():
    sources = [
        {
            "id": "journal:intent",
            "kind": "journal",
            "date": "2026-11-12",
            "observed_at": "2026-11-12T12:00:00Z",
            "text": "Consumer-group isolation was proposed to investigate SSE disconnects.",
        },
        {
            "id": "journal:result",
            "kind": "journal",
            "date": "2026-11-13",
            "observed_at": "2026-11-13T17:00:00Z",
            "text": "PR #485 merged. Staging was queued; its effect remains unconfirmed.",
        },
        {
            "id": "commit:" + "b" * 40,
            "kind": "git_commit",
            "date": "2026-11-13",
            "observed_at": "2026-11-13T14:12:00-03:00",
            "sha": "b" * 40,
            "text": "Commit on principal branch: isolate live consumer groups (#485)",
        },
    ]
    snapshot = {
        "operation": "reports",
        "input": {
            "format_version": 2,
            "kind": "weekly",
            "period_start": "2026-11-09",
            "period_end": "2026-11-15",
            "sources": sources,
        },
    }
    choices = report_quote_choices(sources)

    def item(text, source):
        return {"text": text, "source_ids": [source], "evidence_quote": choices[source][0]["id"]}

    value = {
        "title": "NBA stream reliability",
        "summary": "Consumer-group isolation reached main as a diagnostic change. "
        "Its effect on SSE failures remains unconfirmed.",
        "summary_source_ids": [sources[0]["id"], sources[1]["id"]],
        "outcomes": [item("PR #485 merged as a diagnostic change.", "journal:result")],
        "topics": [
            {
                "id": "nba-sse",
                "title": "NBA SSE investigation",
                "subtitle": "Testing a consumer-group hypothesis",
                "updates": [
                    {
                        "date": "2026-11-12",
                        "title": "Isolation hypothesis",
                        "detail": "",
                        **item(
                            "Proposed isolating consumer groups to investigate disconnects.",
                            "journal:intent",
                        ),
                    },
                    {
                        "date": "2026-11-13",
                        "title": "Diagnostic change merged",
                        "detail": "Staging was queued at cutoff.",
                        **item(
                            "Merged the change; its effect is not yet established.",
                            "journal:result",
                        ),
                    },
                ],
                "final_state": {
                    "status": "Merged; outcome unconfirmed",
                    "items": [
                        item(
                            "Isolation is merged; the cause of disconnects remains unconfirmed.",
                            "journal:result",
                        )
                    ],
                },
            }
        ],
    }
    return snapshot, value


def test_chronological_output_schema_and_publication_preserve_intent_and_exact_quotes():
    snapshot, value = fixture()
    built = build_request(snapshot)
    envelope = {
        "schema_version": 1,
        "outcome": "completed",
        "data": value,
        "missing_inputs": [],
        "failure": None,
        "warnings": [],
    }
    schema = completion_schema(built["schema"])
    jsonschema.validate(envelope, schema)
    assert "$defs" in schema and "$defs" not in schema["properties"]["data"]["anyOf"][0]
    result = validate_result(snapshot, envelope)
    assert result["format_version"] == 2
    assert result["merges"][0]["pr_number"] == 485
    assert result["merges"][0]["sha"] == "b" * 40
    assert "Consumer-group isolation" in result["topics"][0]["updates"][0]["evidence_quote"]
    assert value["topics"][0]["updates"][0]["evidence_quote"].startswith("q")
    text = render_report(result)
    assert (
        text.index("Merged to main")
        < text.index("How the work progressed")
        < text.index("Final state")
    )
    assert "2026-11-12 Isolation hypothesis" in text


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(summary="x" * 421),
        lambda value: value["topics"][0]["updates"][0].update(date="2026-11-13"),
        lambda value: value["topics"][0]["updates"][0].update(date="2026-11-16"),
        lambda value: value["topics"][0].update(id="../unsafe"),
        lambda value: value["topics"].append(deepcopy(value["topics"][0])),
    ],
)
def test_invalid_chronological_output_is_not_published(change):
    snapshot, value = fixture()
    change(value)
    with pytest.raises(ValueError):
        validate_result(snapshot, value)


def test_shared_source_definitions_bound_large_native_schema():
    snapshot, _ = fixture()
    snapshot["input"]["sources"] = [
        {
            "id": f"journal:{n:064x}",
            "date": "2026-11-13",
            "text": "\n".join(f"Exact excerpt number {j} in this source." for j in range(6)),
        }
        for n in range(346)
    ]
    schema = completion_schema(build_request(snapshot)["schema"])
    assert len(json.dumps(schema).encode()) < 100000


@pytest.mark.parametrize("policy,maximum", [(4, 12), (5, 6)])
def test_monthly_week_milestones_are_bounded_without_breaking_prepared_legacy_jobs(policy, maximum):
    snapshot, value = fixture()
    snapshot["input"].update(kind="monthly", period_start="2026-11-01", period_end="2026-11-30")
    snapshot["report"] = {"coverage": {"policy": policy}}
    schema = build_request(snapshot)["schema"]
    assert schema["properties"]["topics"]["items"]["properties"]["updates"]["maxItems"] == maximum
    value["topics"][0]["updates"] = [deepcopy(value["topics"][0]["updates"][0])] * (maximum + 1)
    with pytest.raises(ValueError, match="topic updates"):
        from services.period_reports import validate_report

        validate_report(snapshot, value)


def test_quote_id_resolves_its_real_origin_without_rewriting_native_evidence():
    snapshot, value = fixture()
    item = value["outcomes"][0]
    item["source_ids"] = ["journal:intent"]
    original = deepcopy(value)
    result = validate_report(snapshot, value)
    assert result["outcomes"][0]["source_ids"] == ["journal:result", "journal:intent"]
    assert result["outcomes"][0]["evidence_quote"] in snapshot["input"]["sources"][1]["text"]
    assert value == original


@pytest.mark.parametrize("failure", ["unknown_source", "unsupported_literal", "citation_bound"])
def test_quote_origin_resolution_keeps_scope_exact_text_and_count_guards(failure):
    snapshot, value = fixture()
    item = value["outcomes"][0]
    if failure == "unknown_source":
        item["source_ids"] = ["foreign:source"]
    elif failure == "unsupported_literal":
        item["evidence_quote"] = "An invented supporting excerpt that does not exist."
    else:
        for i in range(10):
            snapshot["input"]["sources"].append(
                {**snapshot["input"]["sources"][0], "id": f"journal:context-{i}"}
            )
        item["source_ids"] = [
            s["id"] for s in snapshot["input"]["sources"] if s["id"] != "journal:result"
        ]
    with pytest.raises(ValueError):
        validate_report(snapshot, value)


def test_merge_body_is_evidence_without_becoming_the_timeline_heading():
    snapshot, value = fixture()
    snapshot["input"]["sources"][2]["text"] += (
        "\n\nPreserve recovery boundaries across puck recovery.\nFix shutdown boundaries."
    )
    result = validate_report(snapshot, value)
    assert result["merges"][0]["title"] == "isolate live consumer groups (#485)"
    assert "Preserve recovery" in snapshot["input"]["sources"][2]["text"]
