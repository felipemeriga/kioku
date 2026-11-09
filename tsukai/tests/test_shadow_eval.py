"""A subscription limit stops new benchmark work without shrinking the denominator."""

import asyncio
import importlib.util
import json
import time
from pathlib import Path

import pytest

from tsukai.validation import NativeError


@pytest.mark.parametrize("verified_snapshot", [True, False])
def test_subscription_guard_stops_inference_but_records_every_case(
    monkeypatch, capsys, verified_snapshot
):
    path = Path(__file__).resolve().parents[2] / "scripts/benchmarks/shadow_eval.py"
    spec = importlib.util.spec_from_file_location("shadow_eval_quota", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    attempts = []

    class Runner:
        async def verify_version(self):
            pass

        async def run(self, claim, request, emit, **kwargs):
            attempts.append(request.idempotency_key)
            raise NativeError("quota_limited")

    monkeypatch.setattr(module, "Settings", lambda: object())
    monkeypatch.setattr(module, "NativeRunner", lambda _: Runner())
    payload = {
        "subscription_usage": {
            "five_hour": 20,
            "seven_day": 10,
            "observed_at": time.time(),
            "account_verified": True,
        },
        "config": {
            "owner_id": "11111111-1111-4111-8111-111111111111",
            "port": 9512,
            "token": "test-only",
        },
        "system_prompt": "Test only",
        "cases": [
            {
                "id": case,
                "question": "What happened?",
                "domain": "memory",
                "oracle_evidence": "Supplied source",
            }
            for case in ["first", "second"]
        ],
    }
    if not verified_snapshot:
        payload["subscription_usage"] = {}
    asyncio.run(module.run(payload, workers=1))
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert attempts == (["first"] if verified_snapshot else [])
    assert [r["id"] for r in results] == ["first", "second"]
    expected = [
        "quota_limited",
        "not_run_after_quota_limit",
    ]
    if not verified_snapshot:
        expected = ["usage_snapshot_required"] * 2
    assert [r["error_code"] for r in results] == expected
    assert not any(r["success"] for r in results)


@pytest.mark.parametrize(
    "change,code",
    [
        ({"five_hour": 75}, "usage_reserve_reached"),
        ({"seven_day": 80}, "usage_reserve_reached"),
        ({"five_hour": 100}, "usage_reserve_reached"),
        ({"five_hour": None}, "usage_snapshot_required"),
        ({"five_hour": float("nan")}, "usage_snapshot_required"),
        ({"seven_day": True}, "usage_snapshot_required"),
        ({"seven_day": -1}, "usage_snapshot_invalid"),
        ({"account_verified": False}, "usage_account_unverified"),
        ({"observed_at": 0}, "usage_snapshot_stale"),
    ],
)
def test_budget_guard_fails_closed(change, code):
    path = Path(__file__).resolve().parents[2] / "scripts/benchmarks/shadow_eval.py"
    spec = importlib.util.spec_from_file_location("shadow_eval_budget", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    snapshot = {
        "five_hour": 20,
        "seven_day": 10,
        "observed_at": time.time(),
        "account_verified": True,
    }
    assert module.budget_error({"subscription_usage": snapshot}) is None
    assert module.budget_error({"subscription_usage": {**snapshot, **change}}) == code


def test_wrong_native_source_is_rejected_before_launch():
    path = Path(__file__).resolve().parents[2] / "scripts/benchmarks/shadow_eval.py"
    spec = importlib.util.spec_from_file_location("shadow_eval_source", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="expected candidate source"):
        asyncio.run(
            module.run(
                {"config": {"remote": "/unrelated-candidate"}, "cases": [{"id": "source-check"}]},
                workers=1,
            )
        )


def test_parallel_queue_uses_four_workers_and_checks_renewed_lease(monkeypatch, capsys, tmp_path):
    path = Path(__file__).resolve().parents[2] / "scripts/benchmarks/shadow_eval.py"
    spec = importlib.util.spec_from_file_location("shadow_parallel_queue", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lease = tmp_path / "usage.json"
    snapshot = {
        "five_hour": 0,
        "seven_day": 0,
        "observed_at": time.time(),
        "account_verified": True,
    }
    lease.write_text(json.dumps(snapshot))
    active, peak, attempts = 0, 0, []

    class Runner:
        async def verify_version(self):
            pass

        async def run(self, claim, request, emit, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            attempts.append(request.idempotency_key)
            if len(attempts) == 4:
                lease.write_text(json.dumps({**snapshot, "five_hour": 75}))
            await asyncio.sleep(0.01)
            active -= 1
            return {"text": "Supported answer [1]", "usage": {}}

    monkeypatch.setattr(module, "Settings", lambda: object())
    monkeypatch.setattr(module, "NativeRunner", lambda _: Runner())
    payload = {
        "config": {
            "owner_id": "11111111-1111-4111-8111-111111111111",
            "port": 9512,
            "token": "test-only",
            "usage_lease": str(lease),
        },
        "system_prompt": "Test only",
        "cases": [
            {
                "id": f"case-{i}",
                "domain": "memory",
                "question": "Question",
                "oracle_evidence": "Source [1]",
            }
            for i in range(8)
        ],
    }
    asyncio.run(module.run(payload, workers=4))
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert peak == 4 and len(attempts) == 4
    assert len(rows) == 8
    assert sum(row["success"] for row in rows) == 4
    assert [row.get("error_code") for row in rows if not row["success"]] == [
        "usage_reserve_reached"
    ] * 4
