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
