"""Backup subprocess failures never leave an unbounded dump or partial file."""

import importlib.util
import io
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def module():
    path = Path(__file__).resolve().parents[2] / "deploy/hive/kioku/vault/backup.py"
    spec = importlib.util.spec_from_file_location("vault_backup", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


@pytest.mark.parametrize("failure", ["missing-age", "timeout", "exit"])
def test_backup_failure_kills_dump_removes_partial(tmp_path, monkeypatch, failure):
    backup = module()

    class Dump:
        def __init__(self):
            self.stdout = io.BytesIO(b"fake dump")
            self.returncode = None
            self.killed = False

        def poll(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

        def wait(self, timeout):
            return self.returncode

    dump = Dump()

    def spawn(*a, **kw):
        assert kw["stderr"] == subprocess.DEVNULL
        return dump

    def encrypt(*a, **kw):
        assert kw["stderr"] == subprocess.DEVNULL and kw["timeout"] == 180
        if failure == "missing-age":
            raise FileNotFoundError("age absent")
        if failure == "timeout":
            raise subprocess.TimeoutExpired("age", 180)
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(backup.subprocess, "Popen", spawn)
    monkeypatch.setattr(backup.subprocess, "run", encrypt)
    monkeypatch.setattr(
        sys, "argv", ["backup", "--recipient", "fake-public", "--directory", str(tmp_path)]
    )
    with pytest.raises(SystemExit, match="No plaintext or partial"):
        backup.main()
    assert dump.killed and dump.stdout.closed
    assert not list(tmp_path.glob("*.dump.age"))
