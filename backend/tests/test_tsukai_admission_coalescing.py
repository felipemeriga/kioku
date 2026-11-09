"""Subscriber/reconciler races must not multiply remote admission work."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.ai import chat


def test_same_turn_waiters_reread_mapping_after_first_admission_without_serializing_other_turns():
    first_entered, both_waiting, release = (threading.Event() for _ in range(3))
    turn = {"owner_id": "owner", "id": "same-turn"}
    key = ("owner", "same-turn")
    calls = []
    mapping = {}

    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()
            self.guard = threading.Lock()
            self.waiters = 0

        def __enter__(self):
            with self.guard:
                self.waiters += 1
                if self.waiters == 2:
                    both_waiting.set()
            self.lock.acquire()

        def __exit__(self, *args):
            self.lock.release()

    gate = SimpleNamespace(lock=ObservedLock(), users=0)

    def admit(current):
        if current["id"] == "other-turn":
            return {"job_id": "independent"}
        if not mapping:
            calls.append("remote-submit")
            first_entered.set()
            assert release.wait(5)
            mapping["job_id"] = "durable-job"
        return dict(mapping)

    with chat._admission_guard:
        chat._admission_gates[key] = gate
    with patch.object(chat, "_submit_turn", side_effect=admit):
        with ThreadPoolExecutor(max_workers=3) as pool:
            try:
                first = pool.submit(chat.submit_turn, turn)
                assert first_entered.wait(5)
                second = pool.submit(chat.submit_turn, turn)
                assert both_waiting.wait(5)
                other = pool.submit(chat.submit_turn, {**turn, "id": "other-turn"})
                assert other.result(timeout=2) == {"job_id": "independent"}
                assert calls == ["remote-submit"]
            finally:
                release.set()
            assert first.result(timeout=5) == second.result(timeout=5) == mapping
    assert calls == ["remote-submit"]
    assert key not in chat._admission_gates


def test_failed_admission_releases_gate_for_retry_and_does_not_retain_turn_keys():
    turn = {"owner_id": "owner", "id": "failed-turn"}
    with patch.object(
        chat, "_submit_turn", side_effect=[RuntimeError("offline"), {"job_id": "job"}]
    ):
        with pytest.raises(RuntimeError, match="offline"):
            chat.submit_turn(turn)
        assert ("owner", "failed-turn") not in chat._admission_gates
        assert chat.submit_turn(turn) == {"job_id": "job"}
    assert ("owner", "failed-turn") not in chat._admission_gates
