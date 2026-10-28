import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# mihari.py reads SUPABASE_URL at import — set dummy env before importing it.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
# A valid url-safe base64-encoded 32-byte Fernet key (for tests only).
os.environ.setdefault("SECRETS_ENCRYPTION_KEY", "v0t88PIYxMpG7x3vzipn_WR_8Jddrpw4fdgliQeMS_s=")
os.environ.setdefault("KIOKU_MCP_URL", "http://localhost:9999")
os.environ.setdefault("MIHARI_TRIGGER_TOKEN", "test-token")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "mihari"))
import mihari  # noqa: E402


def test_quarter_hour_schedule_covers_every_day():
    times = mihari.parse_schedule("*/15")
    assert len(times) == 96
    assert times[:4] == [(0, 0), (0, 15), (0, 30), (0, 45)]
    assert times[-1] == (23, 45)


def test_activity_only_review_skips_expensive_briefing_generation(monkeypatch):
    monkeypatch.setattr(mihari, "API_URL", "http://api")
    monkeypatch.setattr(mihari, "decrypt", lambda _cipher: "key")
    monkeypatch.setattr(mihari, "run_git", lambda *_a, **_k: (0, "search.py", ""))
    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        if url.endswith("/review-plan"):
            return Response(
                {
                    "selected": ["activity"],
                    "reviewed": ["architecture", "overview", "documentation"],
                }
            )
        return Response({"ok": True})

    monkeypatch.setattr(mihari.requests, "post", post)
    activity = []
    monkeypatch.setattr(mihari, "refresh_activity", lambda *_a, **_k: activity.append(True))
    mihari.review_new_commits(
        Path("/clone"),
        {"folder_id": "f1", "remote_url": "repo", "api_key_encrypted": "encrypted"},
        "a" * 40,
        "b" * 40,
        {},
    )
    assert activity == [True]
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["review-plan", "review-complete"]
    assert calls[-1][1]["reviewed"] == ["architecture", "overview", "documentation"]


def _recent_iso():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _setup_reground(monkeypatch, posted):
    monkeypatch.setattr(mihari, "API_URL", "http://api")
    row = {
        "generated_at": _recent_iso(),
        "content": {
            "sections": {
                "architecture": {
                    "content": {"summary": "A" * 500},
                    "updated_at": _recent_iso(),
                    "updated_by": "mihari:guide-v2",
                },
                "overview": {
                    "content": {"description": "B" * 320},
                    "updated_at": _recent_iso(),
                    "updated_by": "mihari:guide-v2",
                },
            }
        },
    }
    monkeypatch.setattr(mihari, "rest_get", lambda path, params: [row])
    monkeypatch.setattr(mihari, "run_git", lambda *a, **k: (0, "", ""))
    monkeypatch.setattr(mihari, "decrypt", lambda s: "KEY")
    monkeypatch.setattr(mihari.Path, "is_file", lambda self: True)
    monkeypatch.setattr(mihari.Path, "is_dir", lambda self: False)
    monkeypatch.setattr(mihari.Path, "stat", lambda self: type("S", (), {"st_size": 100})())
    monkeypatch.setattr(mihari.Path, "read_text", lambda self, **k: "content")

    class _R:
        ok = True

        def raise_for_status(self):
            pass

        def json(self):
            return {"updated": True, "sections": ["architecture"]}

    def fake_post(*a, **k):
        posted["n"] += 1
        return _R()

    monkeypatch.setattr(mihari.requests, "post", fake_post)


def test_reground_skips_when_not_forced(monkeypatch):
    posted = {"n": 0}
    _setup_reground(monkeypatch, posted)
    mihari.maybe_reground_holistic(
        Path("/clone"),
        {"folder_id": "f1", "remote_url": "r", "api_key_encrypted": "x"},
        {},
    )
    assert posted["n"] == 0  # recent watermark -> gated out


def test_reground_force_bypasses_gates(monkeypatch):
    posted = {"n": 0}
    _setup_reground(monkeypatch, posted)
    mihari.maybe_reground_holistic(
        Path("/clone"),
        {"folder_id": "f1", "remote_url": "r", "api_key_encrypted": "x"},
        {},
        force=True,
    )
    assert posted["n"] == 1  # force -> proceeds to POST /reground


def test_reground_never_posts_when_both_sections_are_user_edited(monkeypatch):
    posted = {"n": 0}
    _setup_reground(monkeypatch, posted)
    monkeypatch.setattr(
        mihari,
        "rest_get",
        lambda *_: [
            {
                "generated_at": _recent_iso(),
                "content": {
                    "sections": {
                        "architecture": {
                            "status": "pinned",
                            "provenance": "user_ui",
                            "updated_at": _recent_iso(),
                        },
                        "overview": {
                            "status": "hybrid",
                            "provenance": "user_ui",
                            "updated_at": _recent_iso(),
                        },
                    }
                },
            }
        ],
    )
    mihari.maybe_reground_holistic(
        Path("/clone"),
        {"folder_id": "f1", "remote_url": "r", "api_key_encrypted": "x"},
        {},
        force=True,
    )
    assert posted["n"] == 0


def test_reground_old_auto_sections_upgrade_once(monkeypatch):
    posted = {"n": 0}
    _setup_reground(monkeypatch, posted)
    monkeypatch.setattr(
        mihari,
        "rest_get",
        lambda *_: [
            {
                "generated_at": _recent_iso(),
                "content": {
                    "sections": {
                        "architecture": {"updated_at": _recent_iso(), "updated_by": "agent_mcp"},
                        "overview": {"updated_at": _recent_iso(), "updated_by": "agent_mcp"},
                    }
                },
            }
        ],
    )
    mihari.maybe_reground_holistic(
        Path("/clone"),
        {"folder_id": "f1", "remote_url": "r", "api_key_encrypted": "x"},
        {},
    )
    assert posted["n"] == 1


def test_reground_does_not_replace_recent_rich_agent_briefing(monkeypatch):
    posted = {"n": 0}
    _setup_reground(monkeypatch, posted)
    monkeypatch.setattr(
        mihari,
        "rest_get",
        lambda *_: [
            {
                "generated_at": _recent_iso(),
                "content": {
                    "sections": {
                        "architecture": {
                            "content": {"summary": "Actual service boundaries. " * 25},
                            "updated_at": _recent_iso(),
                            "updated_by": "agent_mcp",
                        },
                        "overview": {
                            "content": {"description": "Actual purpose. " * 25},
                            "updated_at": _recent_iso(),
                            "updated_by": "agent_mcp",
                        },
                    }
                },
            }
        ],
    )
    mihari.maybe_reground_holistic(
        Path("/clone"),
        {"folder_id": "f1", "remote_url": "r", "api_key_encrypted": "x"},
        {},
    )
    assert posted["n"] == 0


def test_failed_reground_attempt_has_cooldown_on_same_head(monkeypatch, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / "README.md").write_text("The API accepts requests.\n")
    monkeypatch.setattr(mihari, "API_URL", "http://api")
    monkeypatch.setattr(mihari, "decrypt", lambda *_: "KEY")
    monkeypatch.setattr(
        mihari,
        "rest_get",
        lambda *_: [
            {
                "generated_at": _recent_iso(),
                "content": {
                    "sections": {
                        "architecture": {"content": {"summary": "Short"}},
                        "overview": {"content": {"description": "Short"}},
                    }
                },
            }
        ],
    )

    def git(args, *_rest, **_kwargs):
        if args[:2] == ["rev-parse", "HEAD"]:
            return 0, "abc123", ""
        return 0, "", ""

    monkeypatch.setattr(mihari, "run_git", git)
    posted = []

    class Response:
        ok = True

        def raise_for_status(self): ...

        def json(self):
            return {"updated": False}

    monkeypatch.setattr(mihari.requests, "post", lambda *a, **k: posted.append(k) or Response())
    repo = {"folder_id": "f1", "remote_url": "r", "api_key_encrypted": "x"}
    mihari.maybe_reground_holistic(tmp_path, repo, {})
    mihari.maybe_reground_holistic(tmp_path, repo, {})
    assert len(posted) == 1


def test_guide_upgrade_uses_grounded_repo_context_without_new_commits(monkeypatch, tmp_path):
    (tmp_path / "README.md").write_text("Start the API with make api.\n")
    (tmp_path / "Makefile").write_text("api:\n\tuv run uvicorn main:app\n")
    monkeypatch.setattr(mihari, "API_URL", "http://api")
    monkeypatch.setattr(
        mihari,
        "rest_get",
        lambda *_: [
            {
                "generated_at": _recent_iso(),
                "content": {
                    "sections": {
                        "how_it_runs": {
                            "content": {"requirements": [], "local_dev": "make api"},
                            "updated_at": _recent_iso(),
                            "updated_by": "agent_mcp",
                        }
                    }
                },
            }
        ],
    )
    monkeypatch.setattr(mihari, "run_git", lambda *a, **k: (0, "", ""))
    monkeypatch.setattr(mihari, "decrypt", lambda *_: "KEY")
    posted = []

    class Response:
        ok = True

        def raise_for_status(self):
            pass

        def json(self):
            return {"updated": True}

    monkeypatch.setattr(
        mihari.requests, "post", lambda *a, **k: posted.append(k["json"]) or Response()
    )
    mihari.refresh_sections(
        tmp_path,
        {"folder_id": "f1", "remote_url": "r", "api_key_encrypted": "x"},
        {},
        force_guide=True,
    )
    assert len(posted) == 1
    assert posted[0]["section"] == "how_it_runs"
    assert any(f["path"] == "README.md" and f["role"] == "context" for f in posted[0]["files"])


def test_section_refresh_no_change_after_upgrade_makes_no_model_call(monkeypatch, tmp_path):
    (tmp_path / "README.md").write_text("Start the API with make api.\n")
    monkeypatch.setattr(mihari, "API_URL", "http://api")
    monkeypatch.setattr(
        mihari,
        "rest_get",
        lambda *_: [
            {
                "generated_at": _recent_iso(),
                "content": {
                    "sections": {
                        "how_it_runs": {
                            "content": {"requirements": [], "local_dev": "make api"},
                            "updated_at": _recent_iso(),
                            "updated_by": "mihari:guide-v2",
                        },
                        "deployment": {
                            "content": {
                                "environments": [],
                                "how_to_deploy": "CI",
                                "ci_cd_notes": "",
                            },
                            "updated_at": _recent_iso(),
                            "updated_by": "mihari:guide-v2",
                        },
                    }
                },
            }
        ],
    )
    monkeypatch.setattr(mihari, "run_git", lambda *a, **k: (0, "", ""))
    monkeypatch.setattr(mihari, "decrypt", lambda *_: "KEY")
    monkeypatch.setattr(mihari.requests, "post", lambda *a, **k: pytest.fail("unexpected call"))
    mihari.refresh_sections(
        tmp_path,
        {"folder_id": "f1", "remote_url": "r", "api_key_encrypted": "x"},
        {},
        force_guide=True,
    )


def test_force_refresh_sections_uses_selective_review(monkeypatch, tmp_path):
    seen = {}

    class _CM:
        def __enter__(self):
            class F:
                name = str(tmp_path / "k.key")

                def write(self, *_): ...
                def flush(self): ...

            return F()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mihari.tempfile, "NamedTemporaryFile", lambda *a, **k: _CM())
    monkeypatch.setattr(mihari.os, "chmod", lambda *a, **k: None)
    monkeypatch.setattr(mihari, "decrypt", lambda s: "KEY")
    monkeypatch.setattr(mihari, "git_env", lambda p: {})
    # ls-remote returns a sha, fetch/reset succeed.
    monkeypatch.setattr(mihari, "run_git", lambda *a, **k: (0, "deadbeef0000 ref", ""))
    monkeypatch.setattr(mihari, "rest_patch", lambda *a, **k: None)
    monkeypatch.setattr(
        mihari, "rest_get", lambda path, params: [{"name": "repo"}] if path == "folders" else []
    )
    monkeypatch.setattr(mihari, "seed_bindings", lambda *a, **k: None)
    monkeypatch.setattr(mihari, "kioku_index", lambda clone: (True, ""))
    monkeypatch.setattr(
        mihari,
        "review_new_commits",
        lambda _clone, _repo, old, new, _env: seen.__setitem__("range", (old, new)),
    )
    monkeypatch.setattr(  # noqa: E501
        mihari, "compute_freshness", lambda *a, **k: seen.__setitem__("fresh", True)
    )

    # Pretend the clone exists so the fetch/reset branch is taken.
    monkeypatch.setattr(mihari.Path, "exists", lambda self: True)

    repo = {
        "id": "1",
        "remote_url": "r",
        "branch": "main",
        "user_id": "u",
        "folder_id": "f1",
        "api_key_encrypted": "enc",
        "last_sha": "deadbeef0000",
    }
    mihari.force_refresh(repo, {"private_key_encrypted": "enc"}, "sections")

    assert seen["range"] == ("deadbeef0000", "deadbeef0000")
    assert seen.get("fresh") is True


def test_handle_run_rejects_bad_token():
    status, body = mihari.handle_run(
        {"X-Mihari-Token": "wrong"}, '{"folder_id":"f1","target":"index"}'
    )
    assert status == 401


def test_handle_run_bad_target():
    status, body = mihari.handle_run(
        {"X-Mihari-Token": "test-token"}, '{"folder_id":"f1","target":"bogus"}'
    )
    assert status == 422


def test_handle_run_unknown_folder(monkeypatch):
    monkeypatch.setattr(mihari, "find_repo", lambda fid: None)
    status, body = mihari.handle_run(
        {"X-Mihari-Token": "test-token"}, '{"folder_id":"nope","target":"index"}'
    )
    assert status == 404


def test_handle_run_started_and_overlap(monkeypatch):
    monkeypatch.setattr(
        mihari, "find_repo", lambda fid: ({"remote_url": "r", "user_id": "u"}, {"k": 1})
    )
    monkeypatch.setattr(mihari, "rest_post", lambda *a: None)
    monkeypatch.setattr(mihari, "rest_patch", lambda *a: None)
    started = {"n": 0}

    def fake_force(repo, key_row, target):
        started["n"] += 1

    monkeypatch.setattr(mihari, "force_refresh", fake_force)
    # Run the job inline instead of in a thread so the assertion is deterministic.
    monkeypatch.setattr(
        mihari.threading,
        "Thread",
        lambda target, daemon=False: type("T", (), {"start": staticmethod(target)})(),
    )
    status, body = mihari.handle_run(
        {"X-Mihari-Token": "test-token"}, '{"folder_id":"f1","target":"index"}'
    )
    assert status == 202 and body == {"started": True}
    assert started["n"] == 1
    assert mihari._pass_lock.locked() is False  # released in finally


@pytest.mark.parametrize("target", ["index", "sections"])
@pytest.mark.parametrize("fails", [False, True])
def test_refresh_records_terminal_state_even_without_content_changes(monkeypatch, target, fails):
    writes = []
    monkeypatch.setattr(mihari, "_pass_lock", threading.Lock())
    monkeypatch.setattr(mihari, "find_repo", lambda fid: ({"remote_url": "r", "user_id": "u"}, {}))
    monkeypatch.setattr(mihari, "rest_post", lambda path, rows, headers: writes.append(rows[0]))
    monkeypatch.setattr(mihari, "rest_patch", lambda path, params, row: writes.append(row))

    def run(*args):
        assert writes[0][f"{target}_refresh_started_at"]
        if fails:
            raise RuntimeError("sensitive internal error")

    monkeypatch.setattr(mihari, "force_refresh", run)
    monkeypatch.setattr(
        mihari.threading,
        "Thread",
        lambda target, daemon: type("T", (), {"start": staticmethod(target)})(),
    )
    status, _ = mihari.handle_run(
        {"X-Mihari-Token": "test-token"}, '{"folder_id":"f1","target":"' + target + '"}'
    )
    assert status == 202
    assert writes[0][f"{target}_refresh_finished_at"] is None
    assert writes[1][f"{target}_refresh_finished_at"] >= writes[0][f"{target}_refresh_started_at"]
    assert bool(writes[1][f"{target}_refresh_error"]) == fails
    assert "sensitive" not in str(writes)
    assert not mihari._pass_lock.locked()


def test_refresh_refuses_untracked_job_when_start_write_fails(monkeypatch):
    monkeypatch.setattr(mihari, "_pass_lock", threading.Lock())
    monkeypatch.setattr(mihari, "find_repo", lambda fid: ({"user_id": "u"}, {}))

    def fail(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(mihari, "rest_post", fail)
    status, _ = mihari.handle_run(
        {"X-Mihari-Token": "test-token"}, '{"folder_id":"f1","target":"index"}'
    )
    assert status == 503
    assert not mihari._pass_lock.locked()


def test_health_endpoint_smoke(monkeypatch):
    import http.client

    monkeypatch.setattr(mihari, "TRIGGER_TOKEN", "test-token")
    monkeypatch.setattr(mihari, "TRIGGER_PORT", 8799)
    mihari.start_trigger_server()
    conn = http.client.HTTPConnection("127.0.0.1", 8799, timeout=2)
    conn.request("GET", "/health")
    resp = conn.getresponse()
    assert resp.status == 200
    assert b'"ok"' in resp.read()


def test_legacy_trigger_header_remains_accepted(monkeypatch):
    monkeypatch.setattr(mihari, "find_repo", lambda fid: None)
    status, _ = mihari.handle_run(
        {"X-Watcher-Token": "test-token"}, '{"folder_id":"f1","target":"index"}'
    )
    assert status == 404  # Auth succeeded; the requested repo was not found.
