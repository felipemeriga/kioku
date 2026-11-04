"""A valid queued heavy job must not hit the short API transport deadline."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("operation", ["documentation", "reground"])
def test_heavy_job_can_finish_after_old_transport_wait(monkeypatch, operation):
    for key in ("SUPABASE_URL", "KIOKU_MCP_URL", "KIOKU_API_URL"):
        monkeypatch.setenv(key, "http://fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture")
    monkeypatch.setenv("MIHARI_TSUKAI_SERVICE_TOKEN", "fixture")
    spec = importlib.util.spec_from_file_location(
        "mihari_wait_fixture", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock, polls, publications = [0], [], []

    def response(body):
        return SimpleNamespace(
            json=lambda: body, raise_for_status=lambda: None, ok=True, status_code=200
        )

    def post(url, **_):
        if url.endswith("/prepare"):
            return response(
                {
                    "engine": "tsukai",
                    "url": "http://runner",
                    "capability": "cap",
                    "request": {},
                    "preparation_id": "prep",
                }
            )
        if url.endswith("/v1/jobs"):
            return response({"job_id": "job"})
        publications.append(url)
        return response({"updated": True})

    def get(*_, **__):
        polls.append(clock[0])
        if len(polls) == 1:
            clock[0] = 250
            return response({"status": "queued"})
        return response({"status": "completed"})

    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module.requests, "get", get)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    result = module.maintenance_post(
        "http://fixture/api/mihari/" + operation,
        headers={},
        json={"folder_id": "folder"},
        timeout=120,
    )
    assert result.ok
    assert len(polls) == 2
    assert publications == ["http://fixture/api/mihari/execution/publish"]
