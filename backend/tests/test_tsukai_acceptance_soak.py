"""Supervisor bookkeeping only; these tests are never integrated E2E evidence."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def supervisor():
    path = Path(__file__).parents[2] / "scripts" / "tsukai_acceptance_soak.py"
    spec = importlib.util.spec_from_file_location("soak", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unready_operator_gate_cannot_create_clock(supervisor, tmp_path):
    with pytest.raises(ValueError, match="readiness"):
        supervisor.supervise({"ready": False}, tmp_path / "run", 14460)
    assert not (tmp_path / "run").exists()


def test_failure_blocks_credit_until_probe_recovers(supervisor, monkeypatch, tmp_path):
    clock = [0.0]
    outcomes = iter([1, 0, 0])
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        supervisor.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    monkeypatch.setattr(
        supervisor.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=next(outcomes))
    )
    plan = {
        "ready": True,
        "build": "unit-only",
        "target": "unit-only",
        "cases": [{"name": "probe", "argv": ["unit-only"], "every": 30, "timeout": 1}],
    }
    result = supervisor.supervise(plan, tmp_path / "run", 30)
    assert result["healthy_seconds"] == 30
    assert result["started_monotonic"] == 0
    assert result["pid"] > 0
    assert result["wall_seconds"] == 60
    assert result["counts"]["probe"] == {"passed": 2, "failed": 1}
    records = [
        json.loads(line) for line in (tmp_path / "run/events.jsonl").read_text().splitlines()
    ]
    assert records[2]["healthy_seconds"] == 0
    assert records[-1]["event"] == "duration_met"


def test_output_directory_cannot_be_reused(supervisor, tmp_path):
    plan = {
        "ready": True,
        "build": "unit-only",
        "target": "unit-only",
        "cases": [{"name": "probe", "argv": ["unit-only"], "every": 30, "timeout": 1}],
    }
    with pytest.raises(FileExistsError):
        supervisor.supervise(plan, tmp_path, 30)


def test_only_successful_probe_duration_earns_credit(supervisor, monkeypatch, tmp_path):
    clock = [0.0]
    calls = [0]
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        supervisor.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )

    def execute(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            clock[0] += 5
            raise supervisor.subprocess.TimeoutExpired("unit-only", 5)
        clock[0] += 7
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(supervisor.subprocess, "run", execute)
    plan = {
        "ready": True,
        "build": "unit-only",
        "target": "unit-only",
        "cases": [{"name": "probe", "argv": ["unit-only"], "every": 30, "timeout": 5}],
    }
    result = supervisor.supervise(plan, tmp_path / "run", 7)
    assert result["healthy_seconds"] == 7
    assert result["wall_seconds"] == 37
    assert result["counts"]["probe"] == {"passed": 1, "failed": 1}
