"""A historical report loads Git for its actual period, not a recent lookback."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def worker(monkeypatch, tmp_path):
    for key in ("SUPABASE_URL", "KIOKU_MCP_URL", "KIOKU_API_URL"):
        monkeypatch.setenv(key, "http://fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture")
    spec = importlib.util.spec_from_file_location(
        "report_worker", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "DATA", tmp_path)
    monkeypatch.setattr(module, "decrypt", lambda _: "repository-key")
    repo = {
        "user_id": "owner",
        "folder_id": "folder",
        "remote_url": "git@github.com:example/project.git",
        "api_key_encrypted": "encrypted",
    }
    (tmp_path / "owner" / "folder" / ".git").mkdir(parents=True)
    return module, repo


def response(body):
    return SimpleNamespace(json=lambda: body, raise_for_status=lambda: None, ok=True)


def test_worker_reads_old_period_selected_from_agent_activity(monkeypatch, worker):
    module, repo = worker
    commands = []
    submitted = []

    def git(args, *_, **__):
        commands.append(args)
        if args[0] == "rev-parse":
            return 0, "a" * 40, ""
        if args[0] == "show":
            return 0, "2026-11-13T10:00:00+00:00", ""
        assert "--since=2024-01-08T00:00:00+00:00" in args
        assert "--until=2024-01-15T00:00:00+00:00" in args
        return 0, "b" * 40 + "\x1f2024-01-10T12:00:00+00:00\x1fEarlier merged change (#8)", ""

    monkeypatch.setattr(module, "run_git", git)
    monkeypatch.setattr(
        module,
        "maintenance_control_post",
        lambda *a, **k: response(
            {
                "period": {
                    "kind": "weekly",
                    "period_start": "2024-01-08",
                    "after": "2024-01-08T00:00:00+00:00",
                    "before": "2024-01-15T00:00:00+00:00",
                }
            }
        ),
    )
    monkeypatch.setattr(module.requests, "get", lambda *a, **k: SimpleNamespace(ok=False))
    monkeypatch.setattr(
        module,
        "maintenance_post",
        lambda *a, **k: submitted.append(k["json"]) or response({"updated": False}),
    )
    module.refresh_repo_reports(repo)
    assert submitted[0]["period_start"] == "2024-01-08"
    assert submitted[0]["report_kind"] == "weekly"
    assert submitted[0]["commits"][0]["at"].startswith("2024-01-10")
    assert not any("100 days" in str(command) for command in commands)


def test_worker_skips_git_history_and_model_when_all_reports_are_current(monkeypatch, worker):
    module, repo = worker

    def git(args, *_, **__):
        assert args[0] in ("rev-parse", "show")
        return 0, ("a" * 40 if args[0] == "rev-parse" else "2026-11-13T10:00:00Z"), ""

    monkeypatch.setattr(module, "run_git", git)
    monkeypatch.setattr(
        module, "maintenance_control_post", lambda *a, **k: response({"period": None})
    )
    monkeypatch.setattr(
        module, "maintenance_post", lambda *a, **k: pytest.fail("No inference is needed")
    )
    module.refresh_repo_reports(repo)
