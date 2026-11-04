"""Consumers validate against the runner's separately owned canonical schemas."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pytest
from jsonschema import validate

from services.ai.client import ExecutionResult
from services.ai.facade import native_completion
from services.ai.scope import ExecutionScope, execution_scope, sign_capability


def schemas():
    root = Path(
        os.getenv("TSUKAI_PROTOCOL_DIR", Path(__file__).resolve().parents[2] / "tsukai/protocol")
    )
    if not root.exists():
        pytest.skip("Runner protocol dependency is in its independently owned PR")
    return root


def test_emitted_completion_matches_canonical_request_and_capability(monkeypatch):
    root = schemas()
    monkeypatch.setenv("TSUKAI_NATIVE_TASKS", "query_rewrite")
    monkeypatch.setenv("TSUKAI_CREDENTIAL_OWNER_ID", "owner")
    monkeypatch.setenv("TSUKAI_CAPABILITY_KEY", "f" * 32)
    client = MagicMock()
    client.complete.return_value = ExecutionResult(
        "job", "rewritten", None, None, "session", "attempt"
    )
    scope = ExecutionScope("owner", ("folder",), caller="mcp")
    with (
        execution_scope(scope),
        patch("services.ai.facade.client_for", return_value=client),
        patch("services.ai.facade.record_job_usage"),
    ):
        native_completion(
            operation="query_rewrite",
            model="claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": "query"}],
            system=None,
            max_tokens=256,
            tools=None,
        )
    request = client.complete.call_args.args[0]
    validate(request, json.loads((root / "job-request.schema.json").read_text()))
    token = sign_capability(scope, "query_rewrite", "completion", request=request)
    capability = jwt.decode(token, "f" * 32, audience="tsukai", algorithms=["HS256"])
    validate(capability, json.loads((root / "capability.schema.json").read_text()))
