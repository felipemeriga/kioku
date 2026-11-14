"""Chronological reports preserve intent, dated updates, and exact provenance."""

import json
from copy import deepcopy

import jsonschema
import pytest

from services.maintenance.operations import build_request, completion_schema, validate_result
from services.period_reports import (
    render_report,
    report_aliases,
    report_choices,
    report_parts,
    report_quote_choices,
    validate_report,
)


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


def compact_fixture():
    snapshot, value = fixture()
    snapshot["report"] = {"coverage": {"policy": 8}}
    reverse = {source: alias for alias, source in report_aliases(snapshot).items()}

    def compact(node):
        if isinstance(node, dict):
            for key, child in node.items():
                if key in ("source_ids", "summary_source_ids"):
                    node[key] = [reverse[item] for item in child]
                else:
                    compact(child)
        elif isinstance(node, list):
            for child in node:
                compact(child)

    compact(value)
    return snapshot, value


def test_compact_source_references_restore_exact_provenance_without_mutating_native_output():
    snapshot, value = compact_fixture()
    snapshot["current"] = {"summary": "Obsolete invented notarization status must not be evidence."}
    original = deepcopy(value)
    built = build_request(snapshot)
    assert built["schema"]["$defs"]["report_source"]["enum"] == ["s0", "s1", "s2"]
    assert "Obsolete invented notarization status" not in built["prompt"]
    assert "journal:intent" not in built["prompt"]
    assert "Evidence choices:" not in built["prompt"]
    projected = json.loads(built["prompt"].split("EVIDENCE SNAPSHOT:\n", 1)[1])
    aliases = report_aliases(snapshot)
    originals = {source["id"]: source for source in snapshot["input"]["sources"]}
    for source in projected["input"]["sources"]:
        assert "text" not in source
        assert (
            "".join(part["text"] for part in source["parts"])
            == originals[aliases[source["id"]]]["text"]
        )
    jsonschema.validate(value, built["schema"])
    result = validate_result(snapshot, value)
    assert result["summary_source_ids"] == ["journal:intent", "journal:result"]
    assert result["topics"][0]["updates"][0]["source_ids"] == ["journal:intent"]
    assert value == original


def test_unknown_compact_reference_is_rejected():
    snapshot, value = compact_fixture()
    value["outcomes"][0]["source_ids"] = ["s99999"]
    with pytest.raises(ValueError, match="outside its model context"):
        validate_result(snapshot, value)


def test_complete_merge_inventory_is_retained_when_model_context_is_partial():
    snapshot, value = compact_fixture()
    for i in range(260):
        snapshot["input"]["sources"].append(
            {
                "id": "commit:" + f"{i:040x}",
                "kind": "git_commit",
                "sha": f"{i:040x}",
                "date": "2026-11-13",
                "observed_at": "2026-11-13T00:00:00Z",
                "text": f"Commit on principal branch: merged change number {i}\n" + "x" * 1500,
            }
        )
    aliases = report_aliases(snapshot)
    assert len(aliases) < 263
    assert "s262" not in aliases
    result = validate_result(snapshot, value)
    assert len(result["merges"]) == 261
    assert "commit:" + f"{259:040x}" in result["merges"][0]["source_ids"] or any(
        merge["source_ids"] == ["commit:" + f"{259:040x}"] for merge in result["merges"]
    )
    value["outcomes"][0]["source_ids"] = ["s262"]
    with pytest.raises(ValueError, match="outside its model context"):
        validate_result(snapshot, value)


def test_compact_quote_catalog_preserves_late_resolutions_and_legacy_preparations():
    source = {
        "id": "journal:long",
        "text": "\n".join(
            f"Source sentence {i} records an intermediate observation." for i in range(12)
        )
        + "\nAll four review findings are now fixed.",
    }
    legacy = report_quote_choices([source])
    assert len(legacy[source["id"]]) == 6
    snapshot = {
        "report": {"coverage": {"policy": 8}},
        "input": {
            "sources": [{**source, "kind": "journal", "observed_at": "2026-11-13T12:00:00Z"}]
        },
    }
    choices = report_choices(snapshot)[source["id"]]
    assert "All four review findings are now fixed." in choices[-1]["text"]
    assert "".join(part["text"] for part in report_parts(snapshot)[source["id"]]) == source["text"]


def test_compact_native_schema_stays_bounded_for_full_inventory_and_larger_journal_context():
    snapshot, _ = compact_fixture()
    sources = []
    for prefix, kind, count in (
        ("journal:", "journal", 500),
        ("original:", "original", 16),
        ("commit:", "git_commit", 1000),
        ("pull:", "github_pull_request", 100),
    ):
        for i in range(count):
            sources.append(
                {
                    "id": prefix + f"{i:064x}",
                    "kind": kind,
                    "observed_at": "2026-11-13T12:00:00Z",
                    "date": "2026-11-13",
                    "text": "\n".join(f"Exact source sentence number {j}." for j in range(6)),
                }
            )
    snapshot["input"]["sources"] = sources
    built = build_request(snapshot)
    assert len(json.dumps(completion_schema(built["schema"])).encode()) < 120000
    assert 586 < len(built["schema"]["$defs"]["report_source"]["enum"]) < 1616


def test_compact_monthly_report_keeps_distinct_verified_updates_in_the_same_week():
    snapshot, value = compact_fixture()
    snapshot["input"].update(kind="monthly", period_start="2026-11-01", period_end="2026-11-30")
    result = validate_result(snapshot, value)
    assert [update["date"] for update in result["topics"][0]["updates"]] == [
        "2026-11-12",
        "2026-11-13",
    ]


def test_compact_weekly_output_has_a_total_update_bound_before_publication():
    snapshot, value = compact_fixture()
    base = value["topics"][0]
    value["topics"] = [
        {
            **deepcopy(base),
            "id": f"topic-{i}",
            "updates": [deepcopy(base["updates"][0]) for _ in range(7)],
        }
        for i in range(5)
    ]
    with pytest.raises(ValueError, match="Too many report updates"):
        validate_result(snapshot, value)


def test_source_parts_preserve_every_character_including_short_lines_and_unicode():
    snapshot, _ = compact_fixture()
    text = "a\ntrue\n" + ("Evidence with paths, accents: memória /src/file.rs\n" * 20) + "x"
    snapshot["input"]["sources"][0]["text"] = text
    parts = report_parts(snapshot)["journal:intent"]
    assert "".join(part["text"] for part in parts) == text
    assert all(1 <= len(part["text"]) <= 250 for part in parts)
    assert all(part["text"] in text for part in parts if "id" in part)
    assert "id" not in parts[-1] if len(parts[-1]["text"].strip()) < 12 else True


def test_commit_body_reference_does_not_invent_a_merge_pr_number():
    snapshot, value = fixture()
    snapshot["input"]["sources"][2]["text"] = (
        "Commit on principal branch: repair configuration\n\nRelated discussion in #9999."
    )
    result = validate_result(snapshot, value)
    assert result["merges"][0]["pr_number"] is None
    assert result["merges"][0]["title"] == "repair configuration"


def test_context_citation_cannot_launder_a_quote_from_another_day():
    snapshot, value = compact_fixture()
    update = value["topics"][0]["updates"][0]
    update.update(date="2026-11-13", source_ids=["s0", "s1"])
    value["topics"][0]["updates"] = [update]
    with pytest.raises(ValueError, match="quote date does not match"):
        validate_result(snapshot, value)


def test_dated_update_can_keep_older_context_with_a_contemporaneous_quote():
    snapshot, value = compact_fixture()
    update = value["topics"][0]["updates"][1]
    update["source_ids"] = ["s0", "s1"]
    result = validate_result(snapshot, value)
    assert result["topics"][0]["updates"][1]["source_ids"] == ["journal:intent", "journal:result"]


def test_compact_report_keeps_two_evidenced_events_on_the_same_day():
    snapshot, value = compact_fixture()
    for source in snapshot["input"]["sources"]:
        source["date"] = "2026-11-12"
    for update in value["topics"][0]["updates"]:
        update["date"] = "2026-11-12"
    result = validate_result(snapshot, value)
    assert len(result["topics"][0]["updates"]) == 2
    assert (
        result["topics"][0]["updates"][0]["evidence_quote"]
        != result["topics"][0]["updates"][1]["evidence_quote"]
    )


@pytest.mark.parametrize(
    "claim,source",
    [
        (
            "business-api reduced from 41 to 31 routes.",
            "Remove broken routes (41 to 35); type-only query fix (35 to 34); "
            "remove unused helpers (34 to 32); type ServiceConfig (32 to 31).",
        ),
        (
            "Scheduler reduced from 185 to 145 modules.",
            "Remove four scripts (185 to 177); client-node fix (177 to 170); "
            "remove unused NGSS, SMT and cache (170 to 145).",
        ),
    ],
)
def test_unlabeled_source_numbers_cannot_become_route_or_module_counts(claim, source):
    from services.period_reports import validate_numeric_ranges

    with pytest.raises(ValueError, match="lacks evidence for its unit"):
        validate_numeric_ranges(claim, [source])


@pytest.mark.parametrize(
    "claim,source",
    [
        ("Diagnostics fell from 41 to 31 errors.", "Type checking reduced from 41 to 31 errors."),
        ("Counts fell from 41 to 31 errors.", "Initially 41 errors; finally 31 errors."),
        ("Type errors fell from 47 to 41 errors.", "Type errors in Services and clips (47 to 41)."),
        ("Changed from 3 to 4 GiB.", "A 3 GiB test preceded adoption of 4 GiB."),
        ("Added 3 to 4 and left the rest unchanged.", "The inputs were inspected."),
    ],
)
def test_explicit_quantities_and_non_quantity_ranges_are_preserved(claim, source):
    from services.period_reports import validate_numeric_ranges

    validate_numeric_ranges(claim, [source])


def test_final_open_pr_cannot_contradict_its_cited_principal_merge():
    snapshot, value = compact_fixture()
    state = value["topics"][0]["final_state"]
    state["status"] = "PR open"
    state["items"][0]["text"] = "PR #485 remains open for investigation."
    reverse = {source: alias for alias, source in report_aliases(snapshot).items()}
    state["items"][0]["source_ids"].append(reverse["commit:" + "b" * 40])
    with pytest.raises(ValueError, match="contradicts principal-branch merge"):
        validate_report(snapshot, value)


def test_opening_event_does_not_prove_pr_remained_open_at_later_cutoff():
    snapshot, value = compact_fixture()
    snapshot["input"]["cutoff"] = "2026-11-14T10:00:00Z"
    snapshot["input"]["sources"][1]["text"] = "PR #479 opened. Later merge status was not checked."
    state = value["topics"][0]["final_state"]
    state["status"] = "PR open, staging format confirmed"
    state["items"][0]["text"] = "PR #479 introduced the score fallback."
    with pytest.raises(ValueError, match="lacks cutoff evidence"):
        validate_report(snapshot, value)
    state["status"] = "Opened; later status unverified"
    assert validate_report(snapshot, value)


def test_current_open_observation_at_cutoff_is_not_confused_with_later_merge():
    snapshot, value = compact_fixture()
    snapshot["input"]["cutoff"] = "2026-11-13T17:00:00.000001Z"
    snapshot["input"]["sources"][1]["text"] = (
        "PR #285 opened. Production rollout remains unverified."
    )
    state = value["topics"][0]["final_state"]
    state["status"] = "PR open, pending merge"
    state["items"][0]["text"] = "PR #285 contains only the startup command patch."
    assert validate_report(snapshot, value)
