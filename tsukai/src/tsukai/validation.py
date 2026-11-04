"""Bounded structural and task-independent noninteractive validation."""

import json
import re

from jsonschema import Draft202012Validator

from .protocol import CompletionEnvelope


class NativeError(Exception):
    def __init__(self, code, retryable=False, *, uncertain=False, result=None, diagnostic=None):
        self.code, self.retryable = code, retryable
        self.uncertain, self.result, self.diagnostic = uncertain, result, diagnostic
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
        if result.get("subtype") == "success":
            raise NativeError("native_provider_error", diagnostic=provider_diagnostic(result))
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
            raise NativeError(
                "invalid_structured_output",
                True,
                diagnostic=repair_diagnostic(result, [{"message": "structured_output is absent"}]),
            )
        errors = list(Draft202012Validator(req.response_schema).iter_errors(structured))
        if errors:
            raise NativeError(
                "invalid_structured_output", True, diagnostic=repair_diagnostic(result, errors)
            )
        if isinstance(structured, dict) and "outcome" in structured:
            try:
                CompletionEnvelope.model_validate(structured)
            except ValueError as exc:
                raise NativeError(
                    "invalid_completion_envelope",
                    True,
                    diagnostic=repair_diagnostic(result, [{"message": str(exc)}]),
                ) from None
    if not text and structured is None:
        raise NativeError("empty_native_result", True)
    return text, structured


def sanitize_private(value):
    """Redact credential-shaped fields/text before retaining private model diagnostics."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if re.search(
                r"authorization|password|secret|credential|oauth|api[_-]?key|access[_-]?token",
                key,
                re.I,
            )
            else sanitize_private(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_private(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)bearer\s+[a-z0-9._~+/-]+=*", "Bearer [REDACTED]", value)
        return re.sub(r"\bsk-[a-zA-Z0-9_-]{8,}", "[REDACTED]", value)
    return value


def provider_diagnostic(result):
    """Private bounded terminal-error evidence, never a native transcript."""
    errors = result.get("errors", [])
    if not isinstance(errors, list):
        errors = [errors]
    selected = []
    for error in errors[:5]:
        if isinstance(error, str):
            selected.append(error)
        elif isinstance(error, dict):
            selected.append(
                {
                    key: error[key]
                    for key in ("type", "code", "status", "status_code", "message")
                    if key in error and isinstance(error[key], (str, int, bool))
                }
            )
    safe = sanitize_private(
        {
            "subtype": str(result.get("subtype", ""))[:80],
            "errors": selected,
            "result": result.get("result") if isinstance(result.get("result"), str) else None,
        }
    )
    encoded = json.dumps(safe)
    if len(encoded) > 8192:
        return {"provider_error": encoded[:3500], "truncated": True}
    return {"provider_error": safe, "truncated": False}


def repair_diagnostic(result, errors):
    details = []
    for error in errors[:30]:
        if isinstance(error, dict):
            details.append(error)
        else:
            details.append(
                {
                    "path": list(error.absolute_path),
                    "schema_path": list(error.absolute_schema_path),
                    "validator": error.validator,
                    "message": error.message,
                }
            )
    data = sanitize_private(
        {
            "invalid_response": result.get("structured_output", result.get("result")),
            "validation_errors": details,
        }
    )
    encoded = json.dumps(data)
    if len(encoded.encode()) > 65536:
        return {
            "invalid_response": encoded.encode()[:48000].decode(errors="ignore"),
            "validation_errors": [
                {**error, "message": str(error.get("message", ""))[:256]}
                for error in data["validation_errors"][:5]
            ],
            "truncated": True,
        }
    return data
