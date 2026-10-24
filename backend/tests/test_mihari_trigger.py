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


def _recent_iso():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _setup_reground(monkeypatch, posted):
    monkeypatch.setattr(mihari, "API_URL", "http://api")
    row = {
        "generated_at": _recent_iso(),
        "content": {
            "sections": {
                "architecture": {"updated_at": _recent_iso()},
                "important_files": {"content": [{"path": "README.md"}]},
            }
        },
    }
    monkeypatch.setattr(mihari, "rest_get", lambda path, params: [row])
    monkeypatch.setattr(mihari, "run_git", lambda *a, **k: (0, "", ""))
    monkeypatch.setattr(mihari, "decrypt", lambda s: "KEY")
    monkeypatch.setattr(mihari.Path, "is_file", lambda self: True)
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


def test_force_refresh_sections_calls_reground_forced(monkeypatch, tmp_path):
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
    monkeypatch.setattr(  # noqa: E501
        mihari, "refresh_sections", lambda *a, **k: seen.__setitem__("sections", True)
    )
    monkeypatch.setattr(mihari, "refresh_activity", lambda *a, **k: None)
    monkeypatch.setattr(  # noqa: E501
        mihari, "compute_freshness", lambda *a, **k: seen.__setitem__("fresh", True)
    )

    def fake_reground(clone, repo, env, force=False):
        seen["reground_force"] = force

    monkeypatch.setattr(mihari, "maybe_reground_holistic", fake_reground)
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

    assert seen.get("sections") is True
    assert seen.get("reground_force") is True
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
