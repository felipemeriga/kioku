import importlib.util
import json
import os
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
    worker.seed_bindings(clone, "folder", "name", "test-key")
    assert not target.is_symlink()
    assert target.is_file()
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


def test_index_removes_links_preserving_canonical_files(worker, monkeypatch, tmp_path):
    from types import SimpleNamespace

    clone, outside = tmp_path / "repo", tmp_path / "outside"
    skills = clone / ".agents" / "skills"
    skills.mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.py").write_text("external private sentinel")
    canonical = clone / "skills" / "lesson"
    canonical.mkdir(parents=True)
    (canonical / "SKILL.md").write_text("canonical skill")
    (clone / ".mcp.json").write_text("runtime private sentinel")
    (skills / "lesson").symlink_to("../../skills/lesson", target_is_directory=True)
    (clone / "alias.py").symlink_to(".mcp.json")
    (clone / "external.py").symlink_to(outside / "secret.py")
    (clone / "external-dir").symlink_to(outside, target_is_directory=True)
    (clone / "dangling.py").symlink_to("missing")
    (clone / "cycle").symlink_to(".", target_is_directory=True)
    (clone / "cycle-a").symlink_to("cycle-b")
    (clone / "cycle-b").symlink_to("cycle-a")
    calls = []

    def index(*args, **kwargs):
        calls.append(args)
        assert not any(path.is_symlink() for path in clone.rglob("*"))
        assert (canonical / "SKILL.md").read_text() == "canonical skill"
        assert (clone / ".mcp.json").read_text() == "runtime private sentinel"
        return SimpleNamespace(returncode=0, stdout="indexed", stderr="")

    monkeypatch.setattr(worker.subprocess, "run", index)
    assert worker.kioku_index(clone) == (True, "indexed")
    assert len(calls) == 1
    assert (outside / "secret.py").read_text() == "external private sentinel"
    worker.require_link_free_checkout(clone)  # Idempotent preparation.


def test_linked_checkout_root_is_rejected(worker, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").symlink_to("missing")
    clone = tmp_path / "repo"
    clone.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        worker.require_link_free_checkout(clone)
    assert (outside / "sentinel").is_symlink()


def test_link_removal_pins_parent_during_replacement(worker, monkeypatch, tmp_path):
    clone, outside = tmp_path / "repo", tmp_path / "outside"
    (clone / "docs").mkdir(parents=True)
    outside.mkdir()
    (clone / "docs" / "alias").symlink_to("missing")
    (outside / "alias").symlink_to("private-sentinel")
    original_open = worker.os.open

    def swapped_open(path, flags, *args, **kwargs):
        result = original_open(path, flags, *args, **kwargs)
        if path == "docs":
            (clone / "docs").rename(clone / "old-docs")
            (clone / "docs").symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(worker.os, "open", swapped_open)
    worker.require_link_free_checkout(clone)
    assert not (clone / "old-docs" / "alias").is_symlink()
    assert (outside / "alias").is_symlink()


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


@pytest.mark.parametrize("pdf_path", ["guide.pdf", "assets/guide.PDF"])
def test_review_keeps_pdf_inventory_without_decoding_pdf_content(
    worker, monkeypatch, tmp_path, pdf_path
):
    import subprocess

    def git(*args):
        return (
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    *args,
                ],
                cwd=tmp_path,
                capture_output=True,
                check=True,
            )
            .stdout.decode()
            .strip()
        )

    git("init")
    (tmp_path / "source.py").write_text("value = 'before'\n")
    (tmp_path / pdf_path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / pdf_path).write_bytes(b"%PDF-1.7\nold document\n")
    git("add", ".")
    git("commit", "-m", "Initial source")
    before = git("rev-parse", "HEAD")
    (tmp_path / "source.py").write_text("value = 'Olá after'\n")
    # Git sees no NUL in the first 8 KiB and emits this PDF as a text diff.
    (tmp_path / pdf_path).write_bytes(b"%PDF-1.7\n" + b"pdf-private-content\n" * 600 + b"\x80\n")
    (tmp_path / "legacy.txt").write_bytes(b"legacy euro \x80\n")
    git("add", ".")
    git("commit", "-m", "Update source and manual")
    head = git("rev-parse", "HEAD")
    seen = []

    def post(*_args, **kwargs):
        from types import SimpleNamespace

        seen.append(kwargs["json"])
        return SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"selected": [], "reviewed": []}
        )

    monkeypatch.setattr(worker, "API_URL", "http://fixture")
    monkeypatch.setattr(worker, "decrypt", lambda _: "fixture-key")
    monkeypatch.setattr(worker, "maintenance_post", post)
    worker.review_new_commits(
        tmp_path,
        {
            "folder_id": "folder",
            "api_key_encrypted": "encrypted",
            "remote_url": "git@github.com:example/repo.git",
        },
        before,
        head,
        {"PATH": os.environ["PATH"]},
    )
    assert pdf_path in seen[0]["changed_paths"]
    assert "pdf-private-content" not in seen[0]["patch"]
    assert "Olá after" in seen[0]["patch"]
    assert "legacy euro" in seen[0]["patch"]
    assert "Update source and manual" in seen[0]["commits"][0]
