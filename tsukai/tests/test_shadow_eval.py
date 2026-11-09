"""A subscription limit stops new benchmark work without shrinking the denominator."""

import asyncio
import importlib.util
import json
from pathlib import Path

from tsukai.validation import NativeError


def test_quota_limit_stops_future_inference_but_records_every_case(monkeypatch, capsys):
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
            for case in ["first", "second", "third"]
        ],
    }
    asyncio.run(module.run(payload, workers=1))
    results = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert attempts == ["first"]
    assert [r["id"] for r in results] == ["first", "second", "third"]
    assert [r["error_code"] for r in results] == [
        "quota_limited",
        "not_run_after_quota_limit",
        "not_run_after_quota_limit",
    ]
    assert not any(r["success"] for r in results)
