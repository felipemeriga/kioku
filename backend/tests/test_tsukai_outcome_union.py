"""Every machine schema rejects cross-outcome combinations before execution."""

from copy import deepcopy
from itertools import product

import pytest
from jsonschema import Draft202012Validator

from services.ai.contracts import completion_schema
from services.ai.metadata import ENVELOPE_SCHEMA
from services.ai.registry import TASK_POLICIES


def variants():
    yield (
        "metadata",
        ENVELOPE_SCHEMA,
        {
            "operation": "count_files",
            "source_type": None,
            "filename": None,
            "created_after": None,
            "created_before": None,
        },
    )
    for name, policy in TASK_POLICIES.items():
        if not policy.native_verified or policy.profile != "completion":
            continue
        if policy.output == "queries":
            data = {"queries": ["first", "second", "third"]}
        elif policy.output == "json":
            data = (
                {"value": {"updates": []}}
                if name == "folder_summary_rollup"
                else {"value": {"overview": {"purpose": "Purpose", "description": "Evidence"}}}
            )
        else:
            data = {"text": "Resolved task"}
        yield name, completion_schema(name), data


VARIANTS = list(variants())
MISSING = [{"field": "source", "reason": "Source unavailable"}]
FAILURE = {"code": "unsupported", "message": "This operation is unsupported"}


@pytest.mark.parametrize("name,schema,data", VARIANTS, ids=[row[0] for row in VARIANTS])
def test_exact_outcome_data_missing_failure_cross_product(name, schema, data):
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for outcome, has_data, has_missing, has_failure in product(
        ("completed", "needs_input", "failed"), (False, True), (False, True), (False, True)
    ):
        envelope = {
            "schema_version": 1,
            "outcome": outcome,
            "data": deepcopy(data) if has_data else None,
            "missing_inputs": deepcopy(MISSING) if has_missing else [],
            "failure": deepcopy(FAILURE) if has_failure else None,
            "warnings": [],
        }
        expected = (
            (outcome == "completed" and has_data and not has_missing and not has_failure)
            or (outcome == "needs_input" and not has_data and has_missing and not has_failure)
            or (outcome == "failed" and not has_data and not has_missing and has_failure)
        )
        assert validator.is_valid(envelope) == expected, (name, envelope)


@pytest.mark.parametrize("name,schema,data", VARIANTS, ids=[row[0] for row in VARIANTS])
@pytest.mark.parametrize(
    "record",
    [
        {},
        {"field": "", "reason": "missing"},
        {"field": "source", "reason": ""},
        {"field": " ", "reason": "missing"},
        {"field": "source", "reason": "\t"},
        {"field": "source"},
    ],
)
def test_missing_inputs_require_nonblank_field_and_reason(name, schema, data, record):
    envelope = {
        "schema_version": 1,
        "outcome": "needs_input",
        "data": None,
        "missing_inputs": [record],
        "failure": None,
        "warnings": [],
    }
    assert not Draft202012Validator(schema).is_valid(envelope)


@pytest.mark.parametrize("name,schema,data", VARIANTS, ids=[row[0] for row in VARIANTS])
@pytest.mark.parametrize(
    "failure",
    [
        {},
        {"code": "unsupported"},
        {"code": "", "message": "unsupported"},
        {"code": "unsupported", "message": " "},
        {"message": "unsupported"},
        {"untyped": "error"},
    ],
)
def test_failed_requires_a_nonempty_typed_failure(name, schema, data, failure):
    envelope = {
        "schema_version": 1,
        "outcome": "failed",
        "data": None,
        "missing_inputs": [],
        "failure": failure,
        "warnings": [],
    }
    assert not Draft202012Validator(schema).is_valid(envelope)
