"""Headless-service controls must preserve scoped auth, policy and reasoning behavior."""

import json
import os
import uuid
from pathlib import Path

import pytest

from tsukai.config import Settings
from tsukai.native import NativeRunner
from tsukai.protocol import JobRequest


def runner(tmp_path):
    return NativeRunner(
        Settings(
            native_bin=str(Path(__file__).parent / "fixtures/native_cli.py"),
            workspace_dir=str(tmp_path),
            auth_probe=False,
            kill_grace_seconds=0.1,
        )
    )


def request(**kwargs):
    return JobRequest(
        idempotency_key="headless-startup-test",
        caller="backend",
        owner_id="owner",
        operation="rag_agent",
        prompt="INSPECT",
        **kwargs,
    )


@pytest.mark.parametrize("profile", ["chat", "completion"])
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_headless_controls_preserve_auth_and_adaptive_reasoning(
    tmp_path, monkeypatch, profile, effort
):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "fixture-subscription-token")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "native-auth"))
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "ca.pem"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-inherit")
    monkeypatch.setenv("DATABASE_URL", "must-not-inherit")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "0")
    monkeypatch.setenv("DISABLE_AUTOUPDATER", "0")
    monkeypatch.setenv("MAX_THINKING_TOKENS", "9999")
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING", "1")
    req = request(
        profile=profile,
        conversation_id="conversation" if profile == "chat" else None,
        model="claude-haiku-5-5",
        reasoning_effort=effort,
        max_tokens=1024,
    )
    env = runner(tmp_path).environment(req)

    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert env["DISABLE_AUTOUPDATER"] == "1"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "fixture-subscription-token"
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "native-auth")
    assert env["SSL_CERT_FILE"] == str(tmp_path / "ca.pem")
    assert env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "1024"
    for name in (
        "ANTHROPIC_API_KEY",
        "DATABASE_URL",
        "MAX_THINKING_TOKENS",
        "CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING",
    ):
        assert name not in env
    # Restrict child processes, without changing the calling user's environment.
    assert req.reasoning_effort == effort
    assert os.environ["DISABLE_AUTOUPDATER"] == "0"


async def test_headless_controls_reach_subprocess_without_weakening_tool_policy(tmp_path):
    req = request(
        profile="chat",
        conversation_id="conversation",
        model="claude-haiku-5-5",
        reasoning_effort="low",
        tool_allowlist=["search_agent_history", "read_agent_evidence"],
        tool_capability_ref="fixture-scoped-capability",
        folder_ids=["authorized-folder"],
    )
    claim = {
        "attempt": {
            "id": str(uuid.uuid4()),
            "native_session_id": str(uuid.uuid4()),
            "resume": False,
            "counter_segment": str(uuid.uuid4()),
        },
        "workspace": str(tmp_path / "call"),
        "previous_usage": None,
    }

    async def emit(*_args):
        pass

    result = await runner(tmp_path).run(claim, req, emit)
    inspected = json.loads(result["text"])
    args = inspected["args"]
    names = inspected["environment_names"]
    assert "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC" in names
    assert "DISABLE_AUTOUPDATER" in names
    assert args[args.index("--tools") + 1] == ""
    assert args[args.index("--permission-mode") + 1] == "dontAsk"
    assert args[args.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in args
    assert json.loads(args[args.index("--settings") + 1])["disableAllHooks"] is True
    assert args[args.index("--effort") + 1] == "low"
    assert args[args.index("--allowedTools") + 1 :] == [
        "mcp__kioku__search_agent_history",
        "mcp__kioku__read_agent_evidence",
    ]
    assert req.folder_ids == ["authorized-folder"]
    assert req.tool_capability_ref not in args
    assert not list(tmp_path.rglob("mcp-*.json"))
