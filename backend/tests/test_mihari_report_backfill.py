"""A historical report loads Git for its actual period, not a recent lookback."""

import importlib.util
import os
import subprocess
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
            if "--format=%B" in args:
                return 0, "Earlier merged change (#8)\n\nFix review recovery boundaries.", ""
            return 0, "2026-11-13T10:00:00+00:00", ""
        assert "--first-parent" in args
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
    assert "Fix review recovery boundaries." in submitted[0]["commits"][0]["text"]
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


def test_real_merge_history_excludes_feature_branch_commits(monkeypatch, worker):
    module, repo = worker
    clone = module.DATA / repo["user_id"] / repo["folder_id"]

    def git(*args, at="2024-01-01T12:00:00Z"):
        env = {**os.environ, "GIT_AUTHOR_DATE": at, "GIT_COMMITTER_DATE": at}
        return subprocess.run(
            ["git", *args], cwd=clone, env=env, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.test")
    git("commit", "--allow-empty", "-m", "Earlier main baseline")
    git("checkout", "-b", "feature")
    git("commit", "--allow-empty", "-m", "Internal feature work", at="2024-01-10T12:00:00Z")
    git("checkout", "main")
    git("merge", "--no-ff", "feature", "-m", "Merge pull request #8", at="2024-01-11T12:00:00Z")
    submitted = []
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
    assert submitted[0]["git_history_mode"] == "first_parent"
    assert [commit["text"] for commit in submitted[0]["commits"]] == [
        "Commit on principal branch: Merge pull request #8"
    ]


def test_bounded_merge_context_keeps_final_subject_and_late_reversal(worker):
    module, _ = worker
    subject = "ci(typecheck): use tsrs instead of the earlier compiler (#257)"
    message = subject + "\n\nInitial compiler migration.\n" + "Intermediate change.\n" * 200
    message += "Final correction: run tsrs, retaining the compatible build toolchain."
    text = module.report_commit_text(subject, message)
    assert text.splitlines()[0] == "Commit on principal branch: " + subject
    assert "Initial compiler migration." in text
    assert "Final correction: run tsrs" in text
    assert "omitted" in text
    assert len(text) <= 1600


def test_public_pr_observation_time_survives_retries_and_changes_only_with_state(worker):
    from datetime import datetime, timezone

    module, repo = worker
    row = {"number": 7, "state": "open", "updated_at": "2026-11-13T12:00:00Z"}
    first = module.report_pull_observations(
        repo, [row], datetime(2026, 11, 13, 13, tzinfo=timezone.utc)
    )
    again = module.report_pull_observations(
        repo, [row], datetime(2026, 11, 17, 13, tzinfo=timezone.utc)
    )
    assert first == again
    row.update(state="closed", merged_at="2026-11-17T14:00:00Z", updated_at="2026-11-17T14:00:00Z")
    changed = module.report_pull_observations(
        repo, [row], datetime(2026, 11, 17, 15, tzinfo=timezone.utc)
    )
    assert changed["7"] == "2026-11-17T15:00:00+00:00"


def test_failed_month_is_persistently_deferred_while_weekly_work_continues(monkeypatch, worker):
    module, repo = worker

    def git(args, *_, **__):
        return (
            0,
            "a" * 40
            if args[0] == "rev-parse"
            else "2026-11-13T12:00:00Z"
            if args[0] == "show"
            else "",
            "",
        )

    monkeypatch.setattr(module, "run_git", git)
    monkeypatch.setattr(module.requests, "get", lambda *a, **k: SimpleNamespace(ok=False))
    plans = []

    def plan(*_, **kwargs):
        plans.append(kwargs["json"])
        kind = "weekly" if kwargs["json"]["deferred_periods"] else "monthly"
        return response(
            {
                "period": {
                    "kind": kind,
                    "period_start": "2026-11-01" if kind == "monthly" else "2026-11-09",
                    "activity_signature": "same-evidence",
                    "after": "2026-11-01T00:00:00Z",
                    "before": "2026-12-01T00:00:00Z",
                }
            }
        )

    monkeypatch.setattr(module, "maintenance_control_post", plan)
    calls = []

    def run(*_, **kwargs):
        calls.append(kwargs["json"]["report_kind"])
        if calls[-1] == "monthly":
            raise RuntimeError("Rejected candidate")
        return response({"updated": True})

    monkeypatch.setattr(module, "maintenance_post", run)
    with pytest.raises(RuntimeError, match="Rejected"):
        module.refresh_repo_reports(repo)
    # The second pass reads durable retry metadata, as a restarted worker does.
    module.refresh_repo_reports(repo)
    assert calls == ["monthly", "weekly"]
    assert plans[1]["deferred_periods"] == [
        {"kind": "monthly", "period_start": "2026-11-01", "activity_signature": None}
    ]
    path, _ = module.report_retry_state(repo)
    assert path.stat().st_mode & 0o777 == 0o600


def test_quota_cooldown_does_not_retry_other_native_jobs_in_same_pass(monkeypatch, worker):
    module, _ = worker
    calls = []
    now = [1000.0]
    monkeypatch.setattr(
        module, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=lambda _: None)
    )

    def submit(*a, **k):
        calls.append(k)
        if len(calls) == 1:
            return SimpleNamespace(status_code=429, json=lambda: {"detail": "quota_limited"})
        return SimpleNamespace(status_code=202, raise_for_status=lambda: None)

    monkeypatch.setattr(module.requests, "post", submit)
    for _ in range(2):
        with pytest.raises(module.MaintenanceDeferred):
            module.submit_native_job("runner", {}, {})
    assert len(calls) == 1
    now[0] += 901
    assert module.submit_native_job("runner", {}, {}).status_code == 202


def test_api_billing_cooldown_is_repository_scoped_and_never_uses_native_fallback(
    monkeypatch, worker
):
    module, _ = worker
    calls = []
    monkeypatch.setattr(
        module, "maintenance_control_post", lambda *a, **k: response({"engine": "api"})
    )

    def api(url, **kwargs):
        calls.append(kwargs["json"]["folder_id"])
        return SimpleNamespace(
            status_code=503,
            json=lambda: {"detail": "Anthropic credits exhausted for the Kioku backend key"},
        )

    monkeypatch.setattr(module.requests, "post", api)
    for folder in ["blocked", "blocked", "another-owner"]:
        with pytest.raises(module.MaintenanceDeferred):
            module.maintenance_post(
                "http://fixture/api/mihari/reports",
                headers={},
                json={"folder_id": folder},
                timeout=30,
            )
    assert calls == ["blocked", "another-owner"]
