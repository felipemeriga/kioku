"""Bounded structural and task-independent noninteractive validation."""

import json
import re

from jsonschema import Draft202012Validator

from .protocol import CompletionEnvelope


class NativeError(Exception):
    def __init__(self, code, retryable=False):
        self.code, self.retryable = code, retryable
        super().__init__(code)


def validate_result(req, result):
    if result.get("is_error") or result.get("subtype", "success") != "success":
        # Only match native text privately; never return its possibly sensitive content.
        error = json.dumps(result.get("errors", [])) + str(result.get("result", ""))
        lower = error.lower()
        if any(
            x in lower
            for x in ("oauth", "authentication", "login", "invalid token", "unauthorized")
        ):
            raise NativeError("reauth_required")
        if any(
            x in lower for x in ("no conversation found", "session not found", "session corrupted")
        ):
            raise NativeError("native_session_missing")
        if any(x in lower for x in ("rate limit", "usage limit", "quota", "overloaded")):
            raise NativeError("quota_limited")
        if "refresh" in lower and "another" in lower:
            raise NativeError("refresh_contention", True)
        raise NativeError(
            "native_" + re.sub(r"[^a-z0-9_]", "", str(result.get("subtype", "error")))[:60]
        )
    if result.get("permission_denials"):
        raise NativeError("interaction_required")
    structured = result.get("structured_output")
    text = result.get("result", "")
    if not isinstance(text, str):
        raise NativeError("invalid_native_result")
    if req.response_schema:
        if structured is None:
            raise NativeError("invalid_structured_output", True)
        errors = list(Draft202012Validator(req.response_schema).iter_errors(structured))
        if errors:
            raise NativeError("invalid_structured_output", True)
        if isinstance(structured, dict) and "outcome" in structured:
            try:
                CompletionEnvelope.model_validate(structured)
            except ValueError:
                raise NativeError("invalid_completion_envelope", True) from None
    if not text and structured is None:
        raise NativeError("empty_native_result", True)
    return text, structured
