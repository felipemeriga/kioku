import json
import uuid
from pathlib import Path

import pytest

from tsukai.config import Settings
from tsukai.native import NativeRunner, native_prompt
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


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("new_contract", [False, True])
def test_history_is_sent_on_rebuild_but_not_duplicated_on_verified_resume(resume, new_contract):
    original = {
        "canonical_history": [{"role": "user", "content": "earlier user decision"}],
        "user_message": "new question",
        "current_turn_evidence": "fresh evidence [1]",
        "time_context": "today in the user timezone",
    }
    req = request(
        json.dumps(original),
        profile="chat",
        conversation_id="conversation",
        metadata={"history_transport": "resume-delta-v1"} if new_contract else {},
    )
    result = json.loads(native_prompt(req, resume))
    assert ("canonical_history" in result) == (not resume or not new_contract)
    assert {k: v for k, v in result.items() if k != "canonical_history"} == {
        k: v for k, v in original.items() if k != "canonical_history"
    }


def test_invalid_versioned_resume_does_not_silently_drop_context():
    req = request(
        "not a context envelope",
        profile="chat",
        conversation_id="conversation",
        metadata={"history_transport": "resume-delta-v1"},
    )
    with pytest.raises(NativeError, match="invalid_chat_context"):
        native_prompt(req, True)


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


async def test_exited_leader_term_ignoring_descendant_is_killed_with_bounded_drain(tmp_path):
    import os
    import subprocess
    import time

    runner = NativeRunner(settings(tmp_path, idle_seconds=0.2))
    child = None

    async def emit(kind, data):
        nonlocal child
        if data.get("text", "").startswith("child:"):
            child = int(data["text"].split(":")[1])

    started = time.monotonic()
    try:
        with pytest.raises(NativeError) as error:
            await runner.run(claim(tmp_path), request("ORPHAN"), emit)
        assert error.value.uncertain
        assert child is not None and time.monotonic() - started < 3
        # A reparented zombie may await PID1 reap; it is dead and cannot hold pipes.
        state = subprocess.run(
            ["ps", "-o", "stat=", "-p", str(child)], capture_output=True, text=True
        ).stdout.strip()
        assert not state or state.startswith("Z")
        assert not runner.processes
    finally:
        if child:
            try:
                os.kill(child, 9)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("prompt", ["FOREIGN_INIT", "FOREIGN_FINAL", "MISSING_FINAL_ID", "NO_INIT"])
async def test_native_session_ids_fail_closed(tmp_path, prompt):
    async def emit(*args):
        pass

    with pytest.raises(NativeError, match="native_session_mismatch") as error:
        await NativeRunner(settings(tmp_path)).run(claim(tmp_path), request(prompt), emit)
    assert error.value.uncertain and error.value.result is None


async def test_nonzero_exit_preserves_terminal_evidence_and_counters(tmp_path):
    async def emit(*args):
        pass

    with pytest.raises(NativeError, match="native_process_failed") as error:
        await NativeRunner(settings(tmp_path)).run(claim(tmp_path), request("NONZERO"), emit)
    assert error.value.uncertain
    assert error.value.result["text"] == "Canonical answer."
    assert error.value.result["usage"]["list_equivalent_usd"] == 0.001
    assert not error.value.result["usage"]["complete"]


async def test_per_inference_output_control_is_not_aggregate_harness_budget(tmp_path):
    async def emit(*args):
        pass

    result = await NativeRunner(settings(tmp_path)).run(
        claim(tmp_path), request("AGGREGATE", max_tokens=64), emit
    )
    assert result["usage"]["output_tokens"] == 2000
    assert result["usage"]["requested_max_output_tokens_per_inference"] == 64


async def test_abnormal_exit_dominates_invalid_schema_and_retains_private_diagnostic(tmp_path):
    async def emit(*args):
        pass

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    with pytest.raises(NativeError, match="native_process_failed") as caught:
        await NativeRunner(settings(tmp_path)).run(
            claim(tmp_path), request("NONZERO INVALID", response_schema=schema), emit
        )
    error = caught.value
    assert error.uncertain and not error.retryable
    assert error.result["structured"] == {"answer": 17}
    assert error.result["usage"]["list_equivalent_usd"] == 0.001
    assert not error.result["usage"]["complete"]
    assert error.diagnostic["invalid_response"] == {"answer": 17}
    assert error.diagnostic["validation_errors"][0]["path"] == ["answer"]


async def test_native_root_union_is_wrapped_and_original_outcome_validated(tmp_path):
    from test_structured import envelope_schema

    async def emit(*args):
        pass

    schema = envelope_schema()
    runner = NativeRunner(settings(tmp_path))
    result = await runner.run(
        claim(tmp_path), request("ENVELOPE", response_schema=schema, max_turns=1), emit
    )
    assert result["structured"]["outcome"] == "completed"
    assert "result" not in result["structured"]
    with pytest.raises(NativeError, match="invalid_structured_output"):
        await runner.run(
            claim(tmp_path), request("ENVELOPE BAD_UNION", response_schema=schema), emit
        )
    with pytest.raises(NativeError, match="invalid_structured_output"):
        await runner.run(
            claim(tmp_path), request("ENVELOPE BAD_WRAPPER", response_schema=schema), emit
        )


async def test_logical_and_effective_output_budgets_survive_success_and_failure(tmp_path):
    async def emit(*args):
        pass

    runner = NativeRunner(settings(tmp_path))
    req = request(max_tokens=1024, metadata={"caller_requested_max_tokens": 120})
    assert runner.environment(req)["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "1024"
    result = await runner.run(claim(tmp_path), req, emit)
    assert result["usage"]["requested_max_output_tokens_per_inference"] == 120
    assert result["usage"]["effective_max_output_tokens_per_inference"] == 1024
    with pytest.raises(NativeError) as failed:
        await runner.run(
            claim(tmp_path),
            request("AUTH", max_tokens=1024, metadata={"caller_requested_max_tokens": 120}),
            emit,
        )
    assert failed.value.result["usage"]["requested_max_output_tokens_per_inference"] == 120
    assert failed.value.result["usage"]["effective_max_output_tokens_per_inference"] == 1024


@pytest.mark.parametrize("model", ["claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5"])
@pytest.mark.parametrize("thinking,effort", [(0, "low"), (2048, "high")])
async def test_adaptive_only_models_preserve_deep_effort_without_claiming_fixed_budget(
    tmp_path, model, thinking, effort
):
    async def emit(*args):
        pass

    result = await NativeRunner(settings(tmp_path)).run(
        claim(tmp_path), request("INSPECT", model=model, thinking_tokens=thinking), emit
    )
    inspected = json.loads(result["text"])
    assert inspected["args"][inspected["args"].index("--effort") + 1] == effort
    assert "MAX_THINKING_TOKENS" not in inspected["environment_names"]
    assert "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING" not in inspected["environment_names"]
    assert result["usage"]["thinking_control"] == {
        "mode": "adaptive_effort",
        "effort": effort,
        "requested_thinking_tokens": thinking,
        "fixed_thinking_budget_supported": False,
    }


async def test_heavy_maintenance_uses_its_separate_wall_budget(tmp_path, monkeypatch):
    runner = NativeRunner(settings(tmp_path, wall_seconds=0.001, maintenance_wall_seconds=5))
    req = request(
        response_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }
    ).model_copy(update={"caller": "mihari", "operation": "mihari.documentation"})
    import asyncio

    original = asyncio.create_subprocess_exec
    argv = []

    async def launch(*args, **kwargs):
        argv.extend(args)
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)

    async def emit(*_):
        pass

    result = await runner.run(claim(tmp_path), req, emit)
    assert result["structured"] == {"answer": "grounded"}
    system = argv[argv.index("--system-prompt") + 1]
    assert "Call StructuredOutput directly" in system
    assert "duplicate the document" in system


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
async def test_explicit_effort_overrides_legacy_budget_for_adaptive_models(tmp_path, effort):
    async def emit(*args):
        pass

    result = await NativeRunner(settings(tmp_path)).run(
        claim(tmp_path),
        request("INSPECT", model="claude-haiku-5-5", reasoning_effort=effort, thinking_tokens=2048),
        emit,
    )
    inspected = json.loads(result["text"])
    assert inspected["args"][inspected["args"].index("--effort") + 1] == effort
    assert "MAX_THINKING_TOKENS" not in inspected["environment_names"]
    assert result["usage"]["thinking_control"]["effort"] == effort


@pytest.mark.parametrize("effort,budget", [("low", "0"), ("medium", "2048"), ("high", "4096")])
def test_explicit_fixed_model_effort_maps_to_bounded_budget(tmp_path, effort, budget):
    req = request(model="claude-sonnet-4-6", max_tokens=6000, reasoning_effort=effort)
    assert NativeRunner(settings(tmp_path)).environment(req)["MAX_THINKING_TOKENS"] == budget


def test_legacy_serialization_omits_new_field_but_explicit_effort_is_bound():
    old = request().model_dump(mode="json")
    assert "reasoning_effort" not in old
    assert JobRequest.model_validate(old).model_dump(mode="json") == old
    assert request(reasoning_effort="low").model_dump(mode="json")["reasoning_effort"] == "low"
    with pytest.raises(ValueError):
        request(reasoning_effort="max")
