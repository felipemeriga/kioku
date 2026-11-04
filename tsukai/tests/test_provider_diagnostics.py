import json

import pytest

from tsukai.protocol import JobRequest
from tsukai.validation import NativeError, validate_result


def request():
    return JobRequest(
        idempotency_key="diagnostic",
        caller="backend",
        owner_id="owner",
        operation="test",
        prompt="test",
    )


def test_unknown_provider_error_preserves_private_sanitized_cause_without_retry():
    terminal = {
        "subtype": "success",
        "is_error": True,
        "errors": [
            {
                "type": "invalid_request_error",
                "status_code": 400,
                "message": (
                    "API Error 400: schema rejected. Bearer fake-private-token "
                    "sk-testcredential123456"
                ),
                "password": "private-password",
                "thinking": "hidden-error-reasoning",
            }
        ],
        "result": "Request rejected: sk-anothercredential123456",
        "thinking": "hidden-top-level-reasoning",
        "messages": ["private-transcript"],
        "structured_output": {"secret": "private-output"},
    }
    with pytest.raises(NativeError) as caught:
        validate_result(request(), terminal)
    error = caught.value
    assert error.code == "native_provider_error"
    assert not error.retryable and not error.uncertain
    assert str(error) == "native_provider_error"
    diagnostic = error.diagnostic["provider_error"]
    assert diagnostic["subtype"] == "success"
    assert diagnostic["errors"][0]["type"] == "invalid_request_error"
    assert diagnostic["errors"][0]["status_code"] == 400
    assert "schema rejected" in diagnostic["errors"][0]["message"]
    encoded = json.dumps(error.diagnostic)
    for private in [
        "fake-private-token",
        "sk-testcredential123456",
        "sk-anothercredential123456",
        "private-password",
        "hidden-error-reasoning",
        "hidden-top-level-reasoning",
        "private-transcript",
        "private-output",
    ]:
        assert private not in encoded
    assert "[REDACTED]" in encoded


def test_unknown_provider_diagnostic_is_bounded_even_for_unicode_errors():
    terminal = {
        "subtype": "success",
        "is_error": True,
        "errors": ["界" * 10000] * 50,
        "result": "end",
    }
    with pytest.raises(NativeError) as caught:
        validate_result(request(), terminal)
    assert caught.value.diagnostic["truncated"] is True
    assert len(json.dumps(caught.value.diagnostic).encode()) < 8192
    assert not caught.value.retryable


@pytest.mark.parametrize(
    "text,code",
    [
        ("OAuth authentication required", "reauth_required"),
        ("usage limit exceeded", "quota_limited"),
        ("session not found", "native_session_missing"),
    ],
)
def test_known_provider_failure_classification_is_unchanged(text, code):
    with pytest.raises(NativeError) as caught:
        validate_result(request(), {"subtype": "success", "is_error": True, "errors": [text]})
    assert caught.value.code == code
    assert not caught.value.retryable
