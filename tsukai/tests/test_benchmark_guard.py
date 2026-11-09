"""A stale transitive prompt file and competing coordinators must fail closed."""

import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/benchmarks"))
from benchmark_guard import (  # noqa: E402
    REQUIRED_SOURCES,
    budget_error,
    coordinator_lock,
    prompt_hash,
    source_files,
    verify_sources,
)


@pytest.fixture
def locked_source(tmp_path):
    root = tmp_path / "source"
    for filename in REQUIRED_SOURCES:
        path = root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Production source\n")
    (root / "backend/services/rag.py").write_text('SYSTEM_PROMPT = "Current instructions"\n')
    (root / "backend/services/ai/chat.py").write_text(
        'NATIVE_CHAT_PROMPT = SYSTEM_PROMPT + " current policy"\n'
    )
    lock = {
        "production_commit": "a" * 40,
        "system_prompt_sha256": prompt_hash(root),
        "files": {
            str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_files(root)
        },
    }
    path = tmp_path / "source-lock.json"
    path.write_text(json.dumps(lock))
    return root, {"remote": str(root), "source_lock": str(path)}


def test_transitive_prompt_drift_is_rejected(locked_source):
    root, config = locked_source
    assert verify_sources(config)["file_count"] == len(REQUIRED_SOURCES)
    (root / "backend/services/rag.py").write_text('SYSTEM_PROMPT = "Older instructions"\n')
    with pytest.raises(ValueError, match="backend/services/rag.py"):
        verify_sources(config)


def test_unlocked_extra_python_module_is_rejected(locked_source):
    root, config = locked_source
    (root / "backend/services/unlocked.py").write_text("# Unexpected import\n")
    with pytest.raises(ValueError, match="unlocked.py"):
        verify_sources(config)


def test_installed_module_cannot_replace_the_snapshot(locked_source, tmp_path):
    _, config = locked_source
    with pytest.raises(ValueError, match="outside the production snapshot"):
        verify_sources(config, [tmp_path / "installed/rag.py"])


def test_source_lock_is_required_for_real_remote_runs(tmp_path):
    with pytest.raises(ValueError, match="source lock is required"):
        verify_sources({"remote": str(tmp_path)})


def test_second_coordinator_cannot_admit_parallel_model_work(tmp_path):
    path = tmp_path / "coordinator.lock"
    with coordinator_lock(path):
        with pytest.raises(ValueError, match="Another benchmark coordinator"):
            with coordinator_lock(path):
                pytest.fail("A second coordinator acquired the shared lock")
    with coordinator_lock(path):
        pass


def test_operator_can_renew_or_revoke_the_shared_usage_lease(tmp_path):
    lease = tmp_path / "usage.json"
    payload = {"config": {"usage_lease": str(lease)}}
    snapshot = {
        "five_hour": 0,
        "seven_day": 0,
        "observed_at": time.time(),
        "account_verified": True,
    }
    lease.write_text(json.dumps(snapshot))
    assert budget_error(payload) is None
    lease.write_text(json.dumps({**snapshot, "five_hour": 75}))
    assert budget_error(payload) == "usage_reserve_reached"
    lease.write_text(json.dumps({**snapshot, "observed_at": 0}))
    assert budget_error(payload) == "usage_snapshot_stale"
    lease.write_text("broken write")
    assert budget_error(payload) == "usage_snapshot_required"
