"""Registered, closed completion envelopes and deterministic semantic checks."""

import json
import re

from jsonschema import ValidationError, validate

from services.ai.client import ExecutionError
from services.ai.registry import TASK_POLICIES


def completion_schema(operation: str) -> dict:
    output = TASK_POLICIES[operation].output
    if output == "queries":
        properties = {
            "queries": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": {"type": "string", "minLength": 1, "maxLength": 2000},
            }
        }
    elif output == "json":
        shapes = (
            [
                {"required": ["updates"], "properties": {"updates": {"type": "array"}}},
                {"required": ["selected"], "properties": {"selected": {"type": "array"}}},
                {
                    "required": ["summary", "highlights"],
                    "properties": {"summary": {"type": "string"}, "highlights": {"type": "array"}},
                },
                {
                    "required": ["requirements", "local_dev"],
                    "properties": {
                        "requirements": {"type": "array"},
                        "local_dev": {"type": "string"},
                    },
                },
                {
                    "required": ["environments", "how_to_deploy", "ci_cd_notes"],
                    "properties": {
                        "environments": {"type": "array"},
                        "how_to_deploy": {"type": "string"},
                        "ci_cd_notes": {"type": "string"},
                    },
                },
            ]
            if operation == "folder_summary_rollup"
            else [
                {
                    "required": ["architecture"],
                    "properties": {
                        "architecture": {
                            "type": "object",
                            "required": ["summary", "components", "data_flow"],
                            "properties": {
                                "summary": {"type": "string", "minLength": 1},
                                "data_flow": {"type": "string", "minLength": 1},
                                "components": {"type": "array"},
                            },
                        }
                    },
                },
                {
                    "required": ["overview"],
                    "properties": {
                        "overview": {
                            "type": "object",
                            "required": ["purpose", "description"],
                            "properties": {
                                "purpose": {"type": "string", "minLength": 1},
                                "description": {"type": "string", "minLength": 1},
                            },
                        }
                    },
                },
            ]
        )
        properties = {"value": {"type": "object", "anyOf": shapes}}
    else:
        properties = {
            "text": {"type": "string", "minLength": 1, "maxLength": 100000, "pattern": r"\S"}
        }
    data = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    return completion_envelope(data)


def completion_envelope(data_schema: dict) -> dict:
    """Exact discriminated outcomes, retained in full for host/native validation."""
    nonblank = {"type": "string", "minLength": 1, "pattern": r"\S"}
    missing = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"field": nonblank, "reason": nonblank},
            "required": ["field", "reason"],
            "additionalProperties": False,
        },
    }
    failure = {
        "type": "object",
        "properties": {"code": nonblank, "message": nonblank},
        "required": ["code", "message"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"const": 1},
            "outcome": {"enum": ["completed", "needs_input", "failed"]},
            "data": {"anyOf": [data_schema, {"type": "null"}]},
            "missing_inputs": missing,
            "failure": {"anyOf": [failure, {"type": "null"}]},
            "warnings": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["schema_version", "outcome", "data", "missing_inputs", "failure", "warnings"],
        "oneOf": [
            {
                "properties": {
                    "outcome": {"const": "completed"},
                    "data": data_schema,
                    "missing_inputs": {"maxItems": 0},
                    "failure": {"type": "null"},
                }
            },
            {
                "properties": {
                    "outcome": {"const": "needs_input"},
                    "data": {"type": "null"},
                    "missing_inputs": {"minItems": 1},
                    "failure": {"type": "null"},
                }
            },
            {
                "properties": {
                    "outcome": {"const": "failed"},
                    "data": {"type": "null"},
                    "missing_inputs": {"maxItems": 0},
                    "failure": failure,
                }
            },
        ],
    }


def completion_text(operation: str, structured: dict | None) -> str:
    try:
        validate(structured, completion_schema(operation))
    except ValidationError:
        raise ExecutionError("invalid_completion_envelope") from None
    outcome = structured["outcome"]
    if outcome != "completed":
        raise ExecutionError(outcome, "completion requires separate missing-input/failure handling")
    if structured["data"] is None or structured["missing_inputs"] or structured["failure"]:
        raise ExecutionError("invalid_completion_outcome")
    data = structured["data"]
    output = TASK_POLICIES[operation].output
    if output == "json":
        return json.dumps(data["value"], ensure_ascii=False)
    values = data["queries"] if output == "queries" else [data["text"]]
    clarification = re.compile(
        r"\b(?:(?:could|can|would) you (?:please )?(?:clarify|provide|specify|share|tell)|"
        r"please (?:clarify|provide|specify)|I need (?:more|additional) (?:context|information))\b",
        re.IGNORECASE,
    )
    for value in values:
        if not value.strip() or clarification.search(value):
            raise ExecutionError(
                "interaction_required", "unattended completion requested clarification"
            )
    if operation == "query_rewrite" and len(values[0].split()) > 200:
        raise ExecutionError(
            "invalid_completion_data", "rewritten query exceeds its registered limit"
        )
    return "\n".join(values)
