"""A valid queued heavy job must not hit the short API transport deadline."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("operation", ["documentation", "reground", "review-plan", "learnings"])
def test_queued_native_job_can_finish_after_old_transport_wait(monkeypatch, operation):
    for key in ("SUPABASE_URL", "KIOKU_MCP_URL", "KIOKU_API_URL"):
        monkeypatch.setenv(key, "http://fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture")
    monkeypatch.setenv("MIHARI_TSUKAI_SERVICE_TOKEN", "fixture")
    spec = importlib.util.spec_from_file_location(
        "mihari_wait_fixture", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock, polls, publications, admissions = [0], [], [], []

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
            admissions.append(url)
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
    assert admissions == ["http://runner/v1/jobs"]
    assert publications == ["http://fixture/api/mihari/execution/publish"]


@pytest.mark.parametrize("failure", ["connection", "unavailable", "persistent", "rejected"])
def test_runner_restart_retries_one_unchanged_admission(monkeypatch, failure):
    for key in ("SUPABASE_URL", "KIOKU_MCP_URL", "KIOKU_API_URL"):
        monkeypatch.setenv(key, "http://fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture")
    spec = importlib.util.spec_from_file_location(
        "mihari_admission_fixture", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock, calls = [0], []
    payload = {"idempotency_key": "immutable-request", "prompt": "Original evidence"}

    def post(url, **kwargs):
        calls.append(kwargs["json"])
        assert kwargs["json"] is payload
        if failure == "rejected":
            raise module.requests.HTTPError("403 denied")
        if failure == "connection" and len(calls) == 1:
            raise module.requests.ConnectionError("runner restarting")
        status = (
            503
            if failure == "persistent" or (failure == "unavailable" and len(calls) == 1)
            else 202
        )
        return SimpleNamespace(status_code=status, raise_for_status=lambda: None)

    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    if failure == "rejected":
        with pytest.raises(module.requests.HTTPError):
            module.submit_native_job("http://runner/v1/jobs", {}, payload)
        assert len(calls) == 1 and clock[0] == 0
    elif failure == "persistent":
        with pytest.raises(RuntimeError, match="preparation retained"):
            module.submit_native_job("http://runner/v1/jobs", {}, payload)
        assert clock[0] == 60 and len(calls) < 20
    else:
        assert module.submit_native_job("http://runner/v1/jobs", {}, payload).status_code == 202
        assert len(calls) == 2
    assert payload == {"idempotency_key": "immutable-request", "prompt": "Original evidence"}


@pytest.mark.parametrize("failure", ["connection", "timeout", "unavailable", "persistent", "auth"])
def test_result_reconnect_preserves_job_and_original_deadline(monkeypatch, failure):
    for key in ("SUPABASE_URL", "KIOKU_MCP_URL", "KIOKU_API_URL"):
        monkeypatch.setenv(key, "http://fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture")
    spec = importlib.util.spec_from_file_location(
        "mihari_result_fixture", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock, calls = [0], []
    url = "http://runner/v1/jobs/immutable-job/result"
    capability = {"X-Tsukai-Capability": "bound-to-original-job"}

    def get(request_url, **kwargs):
        calls.append(request_url)
        assert kwargs["headers"] is capability
        if failure == "auth":
            raise module.requests.HTTPError("403 denied")
        if len(calls) == 1 and failure in {"connection", "timeout"}:
            raise (
                module.requests.ConnectionError
                if failure == "connection"
                else module.requests.Timeout
            )("runner restarting")
        status = (
            503
            if failure == "persistent" or (failure == "unavailable" and len(calls) == 1)
            else 200
        )
        return SimpleNamespace(status_code=status, raise_for_status=lambda: None)

    monkeypatch.setattr(module.requests, "get", get)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    if failure == "auth":
        with pytest.raises(module.requests.HTTPError):
            module.read_native_result(url, capability, 30)
        assert len(calls) == 1 and clock[0] == 0
    elif failure == "persistent":
        with pytest.raises(RuntimeError, match="durable job retained"):
            module.read_native_result(url, capability, 30)
        assert clock[0] == 30 and len(calls) < 10
    else:
        assert module.read_native_result(url, capability, 30).status_code == 200
        assert len(calls) == 2
    assert set(calls) == {url}


@pytest.mark.parametrize(
    "failure", ["lost_response", "html_gateway", "persistent", "json_provider", "auth"]
)
def test_idempotent_control_calls_retry_only_transport_and_non_json_gateway(monkeypatch, failure):
    for key in ("SUPABASE_URL", "KIOKU_MCP_URL", "KIOKU_API_URL"):
        monkeypatch.setenv(key, "http://fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture")
    spec = importlib.util.spec_from_file_location(
        "mihari_control_fixture", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock, calls = [0], []
    payload = {"preparation_id": "immutable-preparation", "job_id": "durable-job"}
    auth = {"Authorization": "fixture"}

    def post(url, **kwargs):
        calls.append(url)
        assert kwargs["json"] is payload and kwargs["headers"] is auth
        if failure == "lost_response" and len(calls) == 1:
            raise module.requests.Timeout("response lost after server committed")
        if failure == "auth":
            return SimpleNamespace(status_code=403)
        if failure == "json_provider":
            return SimpleNamespace(
                status_code=502, json=lambda: {"detail": "maintenance execution: quota_limited"}
            )
        if failure == "persistent" or (failure == "html_gateway" and len(calls) == 1):

            def non_json():
                raise ValueError("HTML Bad Gateway")

            return SimpleNamespace(status_code=502, json=non_json)
        return SimpleNamespace(status_code=200)

    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds)
    )
    url = "http://backend/api/mihari/execution/publish"
    if failure == "persistent":
        with pytest.raises(RuntimeError, match="durable preparation retained"):
            module.maintenance_control_post(url, headers=auth, json=payload)
        assert clock[0] == 60 and len(calls) < 20
    else:
        response = module.maintenance_control_post(url, headers=auth, json=payload)
        if failure in {"json_provider", "auth"}:
            assert response.status_code == (502 if failure == "json_provider" else 403)
            assert len(calls) == 1 and clock[0] == 0
        else:
            assert response.status_code == 200 and len(calls) == 2
    assert set(calls) == {url}
