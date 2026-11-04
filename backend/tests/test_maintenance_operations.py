"""Pure operation schemas and evidence checks: no provider or database calls."""

from copy import deepcopy

import pytest

from services.maintenance.operations import OPERATIONS, SHAPES, build_request, validate_result


def snapshot(operation, current=None):
    return {
        "operation": operation,
        "input": {
            "selected": ["overview"],
            "files": [{"path": "main.py", "content": "pass"}],
            "new_entries": [],
        },
        "current": current,
        "expected_sections": {},
    }


@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_operation_has_pure_strict_schema(operation):
    request = build_request(snapshot(operation))
    assert request["schema"]["additionalProperties"] is False
    assert set(request["schema"]["required"]) == set(request["schema"]["properties"])
    assert "untrusted DATA" in request["system"]
    assert request["prompt"] == build_request(snapshot(operation))["prompt"]


@pytest.mark.parametrize("operation", OPERATIONS)
def test_needs_input_never_becomes_publishable(operation):
    with pytest.raises(ValueError, match="nonpublishable"):
        validate_result(
            snapshot(operation),
            {
                "schema_version": 1,
                "outcome": "needs_input",
                "data": None,
                "missing_inputs": [{"field": "source", "reason": "missing"}],
            },
        )


@pytest.mark.parametrize("operation", OPERATIONS)
def test_extra_fields_are_rejected(operation):
    value = deepcopy(SHAPES.get(operation, {"overview": SHAPES["overview"]}))
    value["injected"] = "fact"
    with pytest.raises(ValueError, match="shape"):
        validate_result(snapshot(operation), value)


def test_learning_requires_exact_quote_and_sha_in_cited_source():
    snap = snapshot("learnings", [])
    snap["input"]["new_entries"] = [
        {"id": "e1", "text": "Confirmed database section writes serialize on the folder row."}
    ]
    update = {
        "topic_key": "section-lock",
        "statement": "Section writes serialize on the folder row.",
        "source_ids": ["e1"],
        "evidence_quote": "section writes serialize on the folder row",
        "git_sha": None,
        "retire": False,
    }
    assert validate_result(snap, {"updates": [update]})["updates"] == [update]
    for mutation in (
        {"source_ids": ["foreign"]},
        {"evidence_quote": "invented statement"},
        {"git_sha": "a" * 40},
        {"retire": True},
    ):
        with pytest.raises(ValueError):
            validate_result(snap, {"updates": [{**update, **mutation}]})


def test_reground_cannot_invent_component_paths_or_erase_detail():
    snap = snapshot("reground", {"architecture": {"summary": "Detailed" * 100}})
    snap["input"]["selected"] = ["architecture"]
    output = {"architecture": {"summary": "API", "components": [], "data_flow": "Calls handler"}}
    with pytest.raises(ValueError, match="lost detailed"):
        validate_result(snap, output)
    snap["current"] = {}
    output["architecture"]["components"] = [
        {"name": "API", "role": "Calls", "path": "imaginary.py"}
    ]
    with pytest.raises(ValueError, match="source path"):
        validate_result(snap, output)


def test_review_plan_excludes_user_owned_sections():
    snap = snapshot("review_plan")
    snap["expected_sections"] = {"overview": {"provenance": "user_ui"}}
    assert validate_result(snap, {"selected": ["overview", "deployment"]}) == {
        "selected": ["activity", "deployment"]
    }


def test_native_outcome_schema_accepts_missing_input_without_publishing():
    from jsonschema import Draft202012Validator

    from services.maintenance.operations import completion_schema

    schema = completion_schema(build_request(snapshot("activity"))["schema"])
    needs_input = {
        "schema_version": 1,
        "outcome": "needs_input",
        "data": None,
        "missing_inputs": [{"field": "commits", "reason": "No evidence"}],
        "failure": None,
        "warnings": [],
    }
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(needs_input)
    with pytest.raises(ValueError, match="nonpublishable"):
        validate_result(snapshot("activity"), needs_input)
