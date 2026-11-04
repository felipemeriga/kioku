"""Native tool schema restrictions must not weaken caller outcome validation."""

import pytest
from jsonschema import Draft202012Validator

from tsukai.structured import native_schema, unwrap_native_output


def envelope_schema():
    data = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "schema_version": {"const": 1},
            "outcome": {"enum": ["completed", "needs_input"]},
            "data": {"anyOf": [data, {"type": "null"}]},
            "missing_inputs": {"type": "array", "items": {"type": "object"}},
            "failure": {"type": "null"},
            "warnings": {"type": "array"},
        },
        "required": ["schema_version", "outcome", "data", "missing_inputs", "failure", "warnings"],
        "additionalProperties": False,
        "oneOf": [
            {
                "properties": {
                    "outcome": {"const": "completed"},
                    "data": data,
                    "missing_inputs": {"maxItems": 0},
                }
            },
            {
                "properties": {
                    "outcome": {"const": "needs_input"},
                    "data": {"type": "null"},
                    "missing_inputs": {"minItems": 1},
                }
            },
        ],
    }


@pytest.mark.parametrize(
    "value,valid",
    [
        (
            {
                "schema_version": 1,
                "outcome": "completed",
                "data": {"answer": "ok"},
                "missing_inputs": [],
                "failure": None,
                "warnings": [],
            },
            True,
        ),
        (
            {
                "schema_version": 1,
                "outcome": "needs_input",
                "data": None,
                "missing_inputs": [{"field": "evidence", "reason": "missing"}],
                "failure": None,
                "warnings": [],
            },
            True,
        ),
        (
            {
                "schema_version": 1,
                "outcome": "needs_input",
                "data": {"answer": "partial"},
                "missing_inputs": [{"field": "evidence", "reason": "missing"}],
                "failure": None,
                "warnings": [],
            },
            False,
        ),
    ],
)
def test_wrapper_preserves_discriminated_union(value, valid):
    original = envelope_schema()
    compiled = native_schema(original)
    assert not any(key in compiled for key in ("oneOf", "anyOf", "allOf"))
    assert bool(Draft202012Validator(original).is_valid(value)) == valid
    assert bool(Draft202012Validator(compiled).is_valid({"result": value})) == valid
    assert unwrap_native_output({"result": value}) == value
    assert "oneOf" in original  # Compiler does not mutate the authoritative caller schema.


def test_document_local_refs_are_relocated_losslessly():
    original = {
        "type": "object",
        "$defs": {"answer": {"type": "string"}},
        "properties": {"answer": {"$ref": "#/$defs/answer"}},
        "required": ["answer"],
    }
    compiled = native_schema(original)
    validator = Draft202012Validator(compiled)
    assert validator.is_valid({"result": {"answer": "grounded"}})
    assert not validator.is_valid({"result": {"answer": 17}})
    assert original["properties"]["answer"]["$ref"] == "#/$defs/answer"


@pytest.mark.parametrize(
    "value", [{"answer": "missing wrapper"}, {"result": {}, "extra": 1}, [], None]
)
def test_unwrap_requires_exact_transport_object(value):
    with pytest.raises(ValueError, match="exactly"):
        unwrap_native_output(value)
