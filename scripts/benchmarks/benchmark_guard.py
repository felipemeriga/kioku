"""Fail-closed source and subscription admission checks for private benchmarks."""

import ast
import fcntl
import hashlib
import json
import math
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path

COORDINATOR_LOCK = Path("/tmp/kioku-quality-inference.lock")
REQUIRED_SOURCES = {
    "backend/services/rag.py",
    "backend/services/evidence_prefetch.py",
    "backend/services/tools.py",
    "backend/services/agent_memory.py",
    "backend/services/agent_memory_tools.py",
    "backend/services/ai/chat.py",
    "backend/services/ai/native_tools.py",
    "tsukai/src/tsukai/native.py",
    "tsukai/src/tsukai/protocol.py",
    "tsukai/src/tsukai/store.py",
}


def usage_snapshot(payload):
    lease = payload.get("config", {}).get("usage_lease")
    if lease:
        try:
            value = json.loads(Path(lease).read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}
    return payload.get("subscription_usage") or {}


def budget_error(payload):
    snapshot = usage_snapshot(payload)
    values = [snapshot.get(k) for k in ("five_hour", "seven_day", "observed_at")]
    if any(type(v) not in (float, int) or not math.isfinite(v) for v in values):
        return "usage_snapshot_required"
    five_hour, seven_day, observed_at = values
    if not 0 <= five_hour <= 100 or not 0 <= seven_day <= 100:
        return "usage_snapshot_invalid"
    if snapshot.get("account_verified") is not True:
        return "usage_account_unverified"
    if not -5 <= time.time() - observed_at <= 90:
        return "usage_snapshot_stale"
    if max(five_hour, seven_day) >= 75:
        return "usage_reserve_reached"
    return None


@contextmanager
def coordinator_lock(path=None):
    """One process owns all benchmark inference; its semaphore bounds workers."""
    descriptor = os.open(path or COORDINATOR_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(
                "Another benchmark coordinator owns inference admission"
            ) from exc
        yield
    finally:
        os.close(descriptor)


def source_files(root):
    root = Path(root).resolve()
    return sorted(
        path
        for directory in (root / "backend", root / "tsukai/src")
        for path in directory.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def prompt_hash(root):
    """Read the production constants without importing env-dependent services."""
    root = Path(root)

    def assignment(path, name):
        return next(
            statement.value
            for statement in ast.parse((root / path).read_text()).body
            if isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == name
                for target in statement.targets
            )
        )

    base = ast.literal_eval(assignment("backend/services/rag.py", "SYSTEM_PROMPT"))
    addition = assignment("backend/services/ai/chat.py", "NATIVE_CHAT_PROMPT")
    if not (
        isinstance(addition, ast.BinOp)
        and isinstance(addition.op, ast.Add)
        and isinstance(addition.left, ast.Name)
        and addition.left.id == "SYSTEM_PROMPT"
    ):
        raise ValueError(
            "Production prompt construction changed; source lock needs review"
        )
    value = base + ast.literal_eval(addition.right)
    return hashlib.sha256(value.encode()).hexdigest()


def verify_sources(config, imported_files=()):
    if not config.get("remote"):
        return None  # Local mocked/oracle diagnostics do not satisfy a locked gate.
    root = Path(config["remote"]).resolve()
    try:
        lock = json.loads(Path(config["source_lock"]).read_text())
    except (KeyError, OSError, ValueError) as exc:
        raise ValueError("Production source lock is required") from exc
    expected = lock.get("files", {})
    if not isinstance(expected, dict) or not REQUIRED_SOURCES <= set(expected):
        raise ValueError("Production source lock is incomplete")
    if not re.fullmatch(r"[0-9a-f]{40}", lock.get("production_commit", "")):
        raise ValueError("Production source revision is invalid")
    actual = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_files(root)
    }
    if actual != expected:
        changed = sorted(
            set(actual) ^ set(expected)
            | {
                name
                for name in set(actual) & set(expected)
                if actual[name] != expected[name]
            }
        )
        raise ValueError("Production source mismatch: " + ", ".join(changed[:8]))
    for filename in imported_files:
        try:
            relative = str(Path(filename).resolve().relative_to(root))
        except ValueError as exc:
            raise ValueError(
                "Imported code is outside the production snapshot"
            ) from exc
        if relative not in expected:
            raise ValueError("Imported code is outside the locked production sources")
    if lock.get("system_prompt_sha256") != prompt_hash(root):
        raise ValueError("Production system prompt does not match its source lock")
    return {
        "production_commit": lock["production_commit"],
        "manifest_sha256": hashlib.sha256(
            json.dumps(lock, sort_keys=True).encode()
        ).hexdigest(),
        "system_prompt_sha256": lock["system_prompt_sha256"],
        "file_count": len(actual),
    }
