import importlib.util
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from routes import mihari as api
from services.git_remote import GIT_ENV, GIT_OPTIONS, validate_git_branch, validate_git_remote


@pytest.mark.parametrize(
    "remote",
    [
        "git@github.com:owner/repo.git",
        "git@gitlab.com:group/subgroup/repo.git",
        "https://github.com/owner/repo.git",
        "https://bitbucket.org/owner/repo",
        "ssh://git@github.com/owner/repo.git",
    ],
)
def test_expected_network_remotes_accepted(remote):
    assert validate_git_remote(remote) == remote
    assert api.TestAccessRequest(remote_url=remote).remote_url == remote
    assert api.RegisterRepoRequest(folder_id="folder", remote_url=remote).remote_url == remote


BAD_REMOTES = [
    "file:///data/victim/private",
    "/data/victim/private",
    "../victim/private",
    "ext::sh -c id",
    "--upload-pack=command",
    "https://attacker.invalid/owner/repo",
    "http://github.com/owner/repo",
    "git://github.com/owner/repo",
    "https://github.com.evil.invalid/owner/repo",
    "git@127.0.0.1:owner/repo",
    "https://token@github.com/owner/repo",
    "ssh://-oProxyCommand=x@github.com/a/b",
    "git@github.com:../private",
    "git@github.com:owner/repo;command",
    "https://github.com/owner/repo?redirect=local",
    "https://github.com/a/%2e%2e",
    "https://github.com\n/owner/repo",
]


@pytest.mark.parametrize("remote", BAD_REMOTES)
def test_unsafe_remote_rejected_by_api_and_transport(monkeypatch, remote):
    monkeypatch.delenv("MIHARI_ALLOWED_GIT_HOSTS", raising=False)
    monkeypatch.setattr(api.subprocess, "run", lambda *a, **k: pytest.fail("Git was launched"))
    with pytest.raises(ValueError):
        validate_git_remote(remote)
    with pytest.raises(ValidationError):
        api.RegisterRepoRequest(folder_id="folder", remote_url=remote)
    with pytest.raises(ValidationError):
        api.TestAccessRequest(remote_url=remote)
    with pytest.raises(ValueError):
        api._ls_remote_with_key("unused", remote, "main")


def test_self_hosted_host_requires_explicit_operator_approval(monkeypatch):
    remote = "ssh://git@code.internal:2222/team/repo.git"
    monkeypatch.delenv("MIHARI_ALLOWED_GIT_HOSTS", raising=False)
    with pytest.raises(ValueError):
        validate_git_remote(remote)
    monkeypatch.setenv("MIHARI_ALLOWED_GIT_HOSTS", "code.internal")
    assert validate_git_remote(remote) == remote


@pytest.mark.parametrize(
    "branch", ["--upload-pack=evil", "../main", "a..b", "a.lock", "a@{x", "a\nmain", "", "-main"]
)
def test_branch_cannot_add_options_or_revision_expressions(branch):
    with pytest.raises(ValueError):
        validate_git_branch(branch)


def load_worker(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.invalid")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-only")
    monkeypatch.setenv("KIOKU_MCP_URL", "https://example.invalid/sse")
    monkeypatch.delenv("SECRETS_ENCRYPTION_KEY", raising=False)
    spec = importlib.util.spec_from_file_location(
        "mihari_remote_test", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker


def test_existing_malicious_row_rejected_before_decryption_or_git(monkeypatch):
    worker = load_worker(monkeypatch)
    monkeypatch.setattr(worker, "decrypt", lambda *_: pytest.fail("Secret decrypted"))
    monkeypatch.setattr(worker.subprocess, "run", lambda *a, **k: pytest.fail("Git launched"))
    for action in (worker.process_repo, lambda repo, key: worker.force_refresh(repo, key, "index")):
        with pytest.raises(ValueError):
            action({"remote_url": "file:///data/victim/repo", "branch": "main"}, {})


def test_existing_clone_with_local_origin_cannot_be_fetched(monkeypatch):
    worker = load_worker(monkeypatch)
    commands = []

    def run(args, **kwargs):
        commands.append(args)
        assert "fetch" not in args
        assert kwargs["env"]["GIT_ALLOW_PROTOCOL"] == "ssh:https"
        return SimpleNamespace(returncode=0, stdout="file:///data/victim/repo", stderr="")

    monkeypatch.setattr(worker.subprocess, "run", run)
    with pytest.raises(ValueError):
        worker.run_git(["fetch", "origin", "main"], {}, cwd="/unused")
    assert len(commands) == 1


def test_git_itself_rejects_local_transport_even_without_validator(tmp_path):
    repo = tmp_path / "private.git"
    subprocess.run(["git", "init", "--bare", str(repo)], check=True, capture_output=True)
    result = subprocess.run(
        ["git", *GIT_OPTIONS, "ls-remote", repo.as_uri()],
        env={**os.environ, **GIT_ENV},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "transport 'file' not allowed" in result.stderr
