import json
import uuid
from pathlib import Path

import pytest

from tsukai.config import Settings
from tsukai.native import NativeRunner
from tsukai.protocol import CompletionEnvelope, JobRequest
from tsukai.validation import NativeError, validate_result


def settings(tmp_path, **kw):
    return Settings(
        native_bin=str(Path(__file__).parent / "fixtures/native_cli.py"),
        workspace_dir=str(tmp_path),
        auth_probe=False,
        kill_grace_seconds=0.1,
        **kw,
    )


def claim(tmp_path, resume=False):
    return {
        "attempt": {
            "id": str(uuid.uuid4()),
            "native_session_id": str(uuid.uuid4()),
            "resume": resume,
            "counter_segment": str(uuid.uuid4()),
        },
        "workspace": str(tmp_path / "call"),
        "previous_usage": None,
    }


def request(prompt="answer", **kw):
    return JobRequest(
        idempotency_key="test",
        caller="backend",
        owner_id="owner",
        operation="test",
        prompt=prompt,
        **kw,
    )


async def test_real_subprocess_normalization_and_no_private_events(tmp_path):
    runner = NativeRunner(settings(tmp_path))
    await runner.verify_version()
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    result = await runner.run(claim(tmp_path), request(), emit)
    assert result["text"] == "Canonical answer."
    assert events == [("text.delta", {"text": "Provisional ", "provisional": True})]
    assert result["usage"]["complete"] and result["usage"]["list_equivalent_usd"] == 0.001
    assert "private-diagnostic" not in json.dumps(events)
    assert not list(tmp_path.rglob("mcp-*.json"))


async def test_native_environment_is_allowlisted_and_profile_controls(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "never-inherited")
    monkeypatch.setenv("DATABASE_URL", "never-inherited")

    async def emit(*args):
        pass

    result = await NativeRunner(settings(tmp_path)).run(
        claim(tmp_path), request("INSPECT", max_tokens=777), emit
    )
    inspected = json.loads(result["text"])
    assert "ANTHROPIC_API_KEY" not in inspected["environment_names"]
    assert "DATABASE_URL" not in inspected["environment_names"]
    assert inspected["max_tokens"] == "777"
    assert "--no-session-persistence" in inspected["args"]
    assert inspected["args"][inspected["args"].index("--tools") + 1] == ""
    assert "--resume" not in inspected["args"]


@pytest.mark.parametrize(
    "prompt,code",
    [
        ("PERMISSION", "interaction_required"),
        ("AUTH", "reauth_required"),
        ("MISSING", "native_result_missing"),
    ],
)
async def test_native_typed_failures_reap_process(tmp_path, prompt, code):
    runner = NativeRunner(settings(tmp_path))

    async def emit(*args):
        pass

    with pytest.raises(NativeError, match=code):
        await runner.run(claim(tmp_path), request(prompt), emit)
    assert not runner.processes


async def test_first_event_deadline_and_stderr_overflow(tmp_path):
    async def emit(*args):
        pass

    runner = NativeRunner(settings(tmp_path, first_event_seconds=0.1, spool_bytes=65536))
    with pytest.raises(NativeError, match="first_event_timeout"):
        await runner.run(claim(tmp_path), request("SLEEP"), emit)
    with pytest.raises(NativeError, match="output_overflow"):
        await runner.run(claim(tmp_path), request("STDERR"), emit)
    assert not runner.processes


def test_structured_outcome_and_quoted_questions_are_not_heuristic_errors():
    req = request(response_schema=CompletionEnvelope.model_json_schema())
    for data in ({"documentation": 'The tool asks "Which repository?"'}, {"answer": "Why?"}):
        _, structured = validate_result(
            req,
            {
                "result": "Which example?",
                "structured_output": {"outcome": "completed", "data": data},
            },
        )
        assert structured["outcome"] == "completed"
    _, structured = validate_result(
        req,
        {
            "result": "",
            "structured_output": {
                "outcome": "needs_input",
                "missing_inputs": [{"field": "repository", "reason": "absent"}],
            },
        },
    )
    assert structured["outcome"] == "needs_input"
