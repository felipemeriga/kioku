import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-only")
    monkeypatch.setenv("KIOKU_MCP_URL", "https://example.invalid/sse")
    monkeypatch.delenv("SECRETS_ENCRYPTION_KEY", raising=False)
    spec = importlib.util.spec_from_file_location(
        "mihari_checkout_test", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seed_and_read_regular_checkout(worker, tmp_path):
    worker.seed_bindings(tmp_path, "folder", "name", "test-key")
    assert json.loads(worker.read_repo_text(tmp_path, ".claude/kioku-state.json")) == {
        "folder_id": "folder",
        "folder_name": "name",
    }
    assert (
        json.loads(worker.read_repo_text(tmp_path, ".mcp.json"))["mcpServers"]["kioku"]["headers"][
            "Authorization"
        ]
        == "Bearer test-key"
    )


@pytest.mark.parametrize("path", [".mcp.json", ".claude/kioku-state.json"])
def test_seed_does_not_overwrite_link_target(worker, tmp_path, path):
    clone = tmp_path / "repo"
    clone.mkdir()
    sentinel = tmp_path / "sentinel.json"
    sentinel.write_text('{"private":"sentinel"}')
    target = clone / path
    target.parent.mkdir(exist_ok=True)
    target.symlink_to(sentinel)
    with pytest.raises(OSError):
        worker.seed_bindings(clone, "folder", "name", "test-key")
    assert sentinel.read_text() == '{"private":"sentinel"}'


def test_directory_link_cannot_read_or_write_external_state(worker, tmp_path):
    clone, outside = tmp_path / "repo", tmp_path / "outside"
    clone.mkdir()
    outside.mkdir()
    (outside / "state.json").write_text("sentinel")
    (clone / ".claude").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        worker.read_repo_text(clone, ".claude/state.json")
    with pytest.raises(OSError):
        worker.write_repo_text(clone, ".claude/state.json", "overwrite")
    assert (outside / "state.json").read_text() == "sentinel"


def test_descriptor_reads_refuse_links_traversal_and_oversize(worker, tmp_path):
    (tmp_path / "normal.txt").write_text("12345")
    (tmp_path / "README.md").symlink_to(tmp_path / "normal.txt")
    for name in ("README.md", "../normal.txt", "/normal.txt"):
        with pytest.raises(OSError):
            worker.read_repo_text(tmp_path, name)
    with pytest.raises(OSError):
        worker.read_repo_text(tmp_path, "normal.txt", 4)


def test_index_refuses_links_before_spawning(worker, monkeypatch, tmp_path):
    (tmp_path / "secret.py").symlink_to(tmp_path / "missing")
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **k: pytest.fail("index spawned"))
    with pytest.raises(OSError):
        worker.kioku_index(tmp_path)


def test_open_directory_is_pinned_during_path_replacement(worker, monkeypatch, tmp_path):
    clone, outside = tmp_path / "repo", tmp_path / "outside"
    (clone / "docs").mkdir(parents=True)
    outside.mkdir()
    (clone / "docs" / "README.md").write_text("repository")
    (outside / "README.md").write_text("private sentinel")
    original_open = worker.os.open

    def swapped_open(path, flags, *args, **kwargs):
        result = original_open(path, flags, *args, **kwargs)
        if path == "docs":
            (clone / "docs").rename(clone / "old-docs")
            (clone / "docs").symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(worker.os, "open", swapped_open)
    assert worker.read_repo_text(clone, "docs/README.md") == "repository"


def test_reground_excludes_external_link_from_ai_request(worker, monkeypatch, tmp_path):
    from types import SimpleNamespace

    clone = tmp_path / "repo"
    clone.mkdir()
    (tmp_path / "private.txt").write_text("private sentinel")
    (clone / "README.md").symlink_to(tmp_path / "private.txt")
    (clone / "package.json").write_text('{"name":"safe"}')
    monkeypatch.setattr(worker, "API_URL", "https://example.invalid")
    monkeypatch.setattr(
        worker,
        "rest_get",
        lambda *_: [{"generated_at": "2026-01-01T00:00:00+00:00", "content": {"sections": {}}}],
    )
    monkeypatch.setattr(worker, "run_git", lambda *_a, **_k: (0, "", ""))
    monkeypatch.setattr(worker, "decrypt", lambda _: "test-only")
    requests = []

    def post(*_args, **kwargs):
        requests.append(kwargs["json"])
        return SimpleNamespace(
            ok=True, raise_for_status=lambda: None, json=lambda: {"updated": True}
        )

    monkeypatch.setattr(worker, "maintenance_post", post)
    worker.maybe_reground_holistic(
        clone,
        {"folder_id": "folder", "remote_url": "remote", "api_key_encrypted": "test"},
        {},
        force=True,
    )
    assert len(requests) == 1
    assert requests[0]["files"] == [{"path": "package.json", "content": '{"name":"safe"}'}]
