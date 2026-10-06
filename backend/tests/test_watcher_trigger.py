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
