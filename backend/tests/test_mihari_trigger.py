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


def test_retired_briefing_review_does_not_make_unchanged_head_stale():
    head = "a" * 40
    reviews = {
        "overview": {"head_sha": head, "reviewed_at": "2026-11-02T10:00:00+00:00"},
        "preferences": {"head_sha": "b" * 40, "reviewed_at": "2026-10-28T10:00:00+00:00"},
    }
    current = mihari.current_briefing_reviews(reviews)
    assert list(current) == ["overview"]
    assert all(item["head_sha"] == head for item in current.values())


def test_unchanged_head_never_calls_paid_briefing_review(monkeypatch, tmp_path):
    head = "a" * 40
    clone = tmp_path / "u1" / "f1"
    (clone / ".git").mkdir(parents=True)
    monkeypatch.setattr(mihari, "DATA", tmp_path)
    monkeypatch.setattr(mihari, "decrypt", lambda _: "test-key")
    monkeypatch.setattr(mihari, "git_env", lambda _: {})
    monkeypatch.setattr(mihari, "run_git", lambda *_a, **_k: (0, f"{head} ref", ""))
    monkeypatch.setattr(mihari, "rest_patch", lambda *_a, **_k: None)
    monkeypatch.setattr(mihari, "compute_freshness", lambda *_a, **_k: None)
    monkeypatch.setattr(
        mihari,
        "review_new_commits",
        lambda *_a, **_k: pytest.fail("unchanged HEAD triggered an AI review"),
    )
    repo = {
        "id": "r1",
        "remote_url": "repo",
        "branch": "main",
        "user_id": "u1",
        "folder_id": "f1",
        "last_sha": head,
    }
    mihari.process_repo(repo, {"private_key_encrypted": "encrypted"})


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
    monkeypatch.setattr(mihari, "maintenance_post", post)
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

    monkeypatch.setattr(mihari, "maintenance_post", fake_post)


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

    monkeypatch.setattr(mihari, "maintenance_post", lambda *a, **k: posted.append(k) or Response())
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
        mihari, "maintenance_post", lambda *a, **k: posted.append(k["json"]) or Response()
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


def test_direct_maintenance_sends_model_only_to_runner_and_publishes_job_id(monkeypatch):
    monkeypatch.setattr(mihari, "API_URL", "https://backend")
    monkeypatch.setenv("MIHARI_TSUKAI_SERVICE_TOKEN", "runner-service")
    submitted = {
        "owner_id": "u1",
        "caller": "mihari",
        "profile": "completion",
        "idempotency_key": "immutable",
        "prompt": "supplied evidence",
        "conversation_id": None,
        "tool_allowlist": [],
    }
    calls = []

    class Response:
        status_code = 200

        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/execution/prepare"):
            return Response(
                {
                    "engine": "tsukai",
                    "url": "https://runner",
                    "capability": "bound-token",
                    "preparation_id": "prepared",
                    "request": submitted,
                }
            )
        if url == "https://runner/v1/jobs":
            assert kwargs["json"] == submitted
            assert kwargs["headers"]["X-Tsukai-Capability"] == "bound-token"
            return Response({"job_id": "job-1"})
        assert url.endswith("/execution/publish")
        assert kwargs["json"] == {
            "folder_id": "f1",
            "preparation_id": "prepared",
            "job_id": "job-1",
        }
        return Response({"ok": True, "updated": True})

    monkeypatch.setattr(mihari.requests, "post", post)
    monkeypatch.setattr(
        mihari.requests,
        "get",
        lambda *_a, **_k: Response(
            {"status": "completed", "result": {"text": "untrusted model output"}}
        ),
    )
    result = mihari.maintenance_post(
        "https://backend/api/mihari/activity",
        headers={"Authorization": "Bearer rag_key"},
        json={"folder_id": "f1", "head_sha": "a" * 40},
        timeout=30,
    )
    assert result.json()["updated"]
    assert len(calls) == 3


def test_failed_direct_job_never_calls_publication(monkeypatch):
    monkeypatch.setattr(mihari, "API_URL", "https://backend")
    monkeypatch.setenv("MIHARI_TSUKAI_SERVICE_TOKEN", "runner-service")
    calls = []

    class Response:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    def post(url, **_kwargs):
        calls.append(url)
        if url.endswith("/execution/prepare"):
            return Response(
                {"engine": "tsukai", "url": "https://runner", "capability": "token", "request": {}}
            )
        return Response({"job_id": "job-1"})

    monkeypatch.setattr(mihari.requests, "post", post)
    monkeypatch.setattr(mihari.requests, "get", lambda *_a, **_k: Response({"status": "failed"}))
    with pytest.raises(RuntimeError, match="failed"):
        mihari.maintenance_post(
            "https://backend/api/mihari/activity", headers={}, json={"folder_id": "f1"}, timeout=30
        )
    assert all(not url.endswith("/execution/publish") for url in calls)


def test_partial_pass_retry_skips_activity_completes_review_and_advances_sha(monkeypatch, tmp_path):
    """Worker retry uses the real skip gate and backend review-complete guard.

    The SQL retry fixture independently checks replacement-plan ACK reseeding.
    """
    from fastapi.testclient import TestClient

    from main import app
    from routes import mihari as routes
    from services.maintenance import execution
    from tests.test_maintenance_execution import DB

    head = "b" * 40
    repo = {
        "id": "r1",
        "user_id": "owner",
        "folder_id": "folder",
        "remote_url": "repo",
        "branch": "main",
        "last_sha": "a" * 40,
        "api_key_encrypted": "cipher",
    }
    clone = tmp_path / "owner" / "folder"
    (clone / ".git").mkdir(parents=True)
    state = {"head_sha": head, "selected": ["activity", "deployment"], "acknowledged": []}
    reviews = {}
    db = DB(
        {
            "maintenance_review_passes": [state],
            "repo_freshness": [
                {"folder_id": "folder", "user_id": "owner", "section_reviews": reviews}
            ],
        }
    )
    state.update(folder_id="folder", user_id="owner")
    monkeypatch.setattr(routes, "_api_key_auth", lambda _: ("owner", "folder", "rag_key"))
    monkeypatch.setattr(routes, "get_supabase", lambda: db)
    monkeypatch.setattr("mcp_server._descendant_folder_ids", lambda *_: ["folder"])
    monkeypatch.setenv("TSUKAI_MIHARI_NATIVE", "true")
    monkeypatch.setenv("TSUKAI_CREDENTIAL_OWNER_ID", "owner")
    monkeypatch.setattr(
        execution,
        "capture",
        lambda *_: ({"expected_sections": {"activity": {}}, "input": {}}, None),
    )
    monkeypatch.setattr(mihari, "API_URL", "http://testserver")
    monkeypatch.setattr(mihari, "DATA", tmp_path)
    monkeypatch.setattr(mihari, "decrypt", lambda _: "key")
    monkeypatch.setattr(mihari, "git_env", lambda _: {})
    monkeypatch.setattr(mihari, "run_git", lambda *_a, **_k: (0, head, ""))
    monkeypatch.setattr(mihari, "rest_get", lambda *_: [{"name": "repo"}])
    monkeypatch.setattr(mihari, "seed_bindings", lambda *_: None)
    monkeypatch.setattr(mihari, "kioku_index", lambda *_: (True, ""))
    monkeypatch.setattr(mihari, "compute_freshness", lambda *_: None)
    recorded, plans, activity_skips = [], [], []
    monkeypatch.setattr(
        mihari,
        "rest_patch",
        lambda table, _filters, patch: recorded.append(patch) if table == "watched_repos" else None,
    )
    client = TestClient(app)

    def plan(*_a, **_k):
        plans.append(True)
        # This is the DB state asserted by retry.sql after a replacement plan.
        state["acknowledged"] = [
            name for name in state["selected"] if (reviews.get(name) or {}).get("head_sha") == head
        ]
        return type(
            "Response",
            (),
            {
                "raise_for_status": lambda _: None,
                "json": lambda _: {"selected": state["selected"], "reviewed": state["selected"]},
            },
        )()

    def activity(*_a, **_k):
        if "activity" in reviews:
            result = execution.prepare(db, "owner", "folder", "activity", {"head_sha": head})
            assert result["engine"] == "skip"
            activity_skips.append(True)
        else:
            reviews["activity"] = {"head_sha": head}
            state["acknowledged"].append("activity")

    def deployment(*_a, **_k):
        if len(plans) == 1:
            raise RuntimeError("deployment failed")
        state["acknowledged"].append("deployment")
        reviews["deployment"] = {"head_sha": head}

    monkeypatch.setattr(mihari, "maintenance_post", plan)
    monkeypatch.setattr(mihari, "refresh_activity", activity)
    monkeypatch.setattr(mihari, "refresh_sections", deployment)
    monkeypatch.setattr(
        mihari.requests,
        "post",
        lambda url, **kwargs: client.post("/api/mihari/review-complete", json=kwargs["json"]),
    )
    mihari.process_repo(repo, {"private_key_encrypted": "cipher"})
    assert not any(p.get("last_sha") == head for p in recorded)
    assert (
        client.post(
            "/api/mihari/review-complete",
            json={"folder_id": "folder", "head_sha": head, "reviewed": state["selected"]},
        ).status_code
        == 409
    )
    mihari.process_repo(repo, {"private_key_encrypted": "cipher"})
    assert activity_skips == [True]
    assert recorded[-1]["last_sha"] == head
    assert recorded[-1]["last_error"] is None
    assert (
        client.post(
            "/api/mihari/review-complete",
            json={"folder_id": "folder", "head_sha": head, "reviewed": state["selected"]},
        ).status_code
        == 200
    )
