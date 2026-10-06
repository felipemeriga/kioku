import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# watcher.py reads SUPABASE_URL at import — set dummy env before importing it.
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
# A valid url-safe base64-encoded 32-byte Fernet key (for tests only).
os.environ.setdefault("SECRETS_ENCRYPTION_KEY", "v0t88PIYxMpG7x3vzipn_WR_8Jddrpw4fdgliQeMS_s=")
os.environ.setdefault("KIOKU_MCP_URL", "http://localhost:9999")
os.environ.setdefault("WATCHER_TRIGGER_TOKEN", "test-token")

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "watcher"))
import watcher  # noqa: E402


def _recent_iso():
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _setup_reground(monkeypatch, posted):
    monkeypatch.setattr(watcher, "API_URL", "http://api")
    row = {
        "generated_at": _recent_iso(),
        "content": {
            "sections": {
                "architecture": {"updated_at": _recent_iso()},
                "important_files": {"content": [{"path": "README.md"}]},
            }
        },
    }
    monkeypatch.setattr(watcher, "rest_get", lambda path, params: [row])
    monkeypatch.setattr(watcher, "run_git", lambda *a, **k: (0, "", ""))
    monkeypatch.setattr(watcher, "decrypt", lambda s: "KEY")
    monkeypatch.setattr(watcher.Path, "is_file", lambda self: True)
    monkeypatch.setattr(watcher.Path, "stat", lambda self: type("S", (), {"st_size": 100})())
    monkeypatch.setattr(watcher.Path, "read_text", lambda self, **k: "content")

    class _R:
        ok = True

        def json(self):
            return {"updated": True, "sections": ["architecture"]}

    def fake_post(*a, **k):
        posted["n"] += 1
        return _R()

    monkeypatch.setattr(watcher.requests, "post", fake_post)


def test_reground_skips_when_not_forced(monkeypatch):
    posted = {"n": 0}
    _setup_reground(monkeypatch, posted)
    watcher.maybe_reground_holistic(
        Path("/clone"),
        {"folder_id": "f1", "remote_url": "r", "api_key_encrypted": "x"},
        {},
    )
    assert posted["n"] == 0  # recent watermark -> gated out


def test_reground_force_bypasses_gates(monkeypatch):
    posted = {"n": 0}
    _setup_reground(monkeypatch, posted)
    watcher.maybe_reground_holistic(
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

    monkeypatch.setattr(watcher.tempfile, "NamedTemporaryFile", lambda *a, **k: _CM())
    monkeypatch.setattr(watcher.os, "chmod", lambda *a, **k: None)
    monkeypatch.setattr(watcher, "decrypt", lambda s: "KEY")
    monkeypatch.setattr(watcher, "git_env", lambda p: {})
    # ls-remote returns a sha, fetch/reset succeed.
    monkeypatch.setattr(watcher, "run_git", lambda *a, **k: (0, "deadbeef0000 ref", ""))
    monkeypatch.setattr(watcher, "rest_patch", lambda *a, **k: None)
    monkeypatch.setattr(
        watcher, "rest_get", lambda path, params: [{"name": "repo"}] if path == "folders" else []
    )
    monkeypatch.setattr(watcher, "seed_bindings", lambda *a, **k: None)
    monkeypatch.setattr(watcher, "kioku_index", lambda clone: (True, ""))
    monkeypatch.setattr(  # noqa: E501
        watcher, "refresh_sections", lambda *a, **k: seen.__setitem__("sections", True)
    )
    monkeypatch.setattr(watcher, "refresh_activity", lambda *a, **k: None)
    monkeypatch.setattr(  # noqa: E501
        watcher, "compute_freshness", lambda *a, **k: seen.__setitem__("fresh", True)
    )

    def fake_reground(clone, repo, env, force=False):
        seen["reground_force"] = force

    monkeypatch.setattr(watcher, "maybe_reground_holistic", fake_reground)
    # Pretend the clone exists so the fetch/reset branch is taken.
    monkeypatch.setattr(watcher.Path, "exists", lambda self: True)

    repo = {
        "id": "1",
        "remote_url": "r",
        "branch": "main",
        "user_id": "u",
        "folder_id": "f1",
        "api_key_encrypted": "enc",
        "last_sha": "deadbeef0000",
    }
    watcher.force_refresh(repo, {"private_key_encrypted": "enc"}, "sections")

    assert seen.get("sections") is True
    assert seen.get("reground_force") is True
    assert seen.get("fresh") is True


def test_handle_run_rejects_bad_token():
    status, body = watcher.handle_run(
        {"X-Watcher-Token": "wrong"}, '{"folder_id":"f1","target":"index"}'
    )
    assert status == 401


def test_handle_run_bad_target():
    status, body = watcher.handle_run(
        {"X-Watcher-Token": "test-token"}, '{"folder_id":"f1","target":"bogus"}'
    )
    assert status == 422


def test_handle_run_unknown_folder(monkeypatch):
    monkeypatch.setattr(watcher, "find_repo", lambda fid: None)
    status, body = watcher.handle_run(
        {"X-Watcher-Token": "test-token"}, '{"folder_id":"nope","target":"index"}'
    )
    assert status == 404


def test_handle_run_started_and_overlap(monkeypatch):
    monkeypatch.setattr(watcher, "find_repo", lambda fid: ({"remote_url": "r"}, {"k": 1}))
    started = {"n": 0}

    def fake_force(repo, key_row, target):
        started["n"] += 1

    monkeypatch.setattr(watcher, "force_refresh", fake_force)
    # Run the job inline instead of in a thread so the assertion is deterministic.
    monkeypatch.setattr(
        watcher.threading, "Thread", lambda target, daemon=False: type("T", (), {"start": target})()
    )
    status, body = watcher.handle_run(
        {"X-Watcher-Token": "test-token"}, '{"folder_id":"f1","target":"index"}'
    )
    assert status == 202 and body == {"started": True}
    assert started["n"] == 1
    assert watcher._pass_lock.locked() is False  # released in finally
