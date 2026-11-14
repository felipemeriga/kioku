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


@pytest.mark.parametrize(
    "code,status,expected,backend_code",
    [
        ("native_error_max_turns", "failed", 2, None),
        ("wall_timeout", "failed", 2, None),
        ("quota_limited", "failed", 1, None),
        ("reauth_required", "failed", 1, None),
        ("native_error_max_turns", "uncertain", 1, None),
        ("cancelled", "cancelled", 1, None),
        ("native_error_max_turns", "failed", 1, "wall_timeout"),
    ],
)
def test_budget_repair_is_once_only_for_confirmed_failures(
    monkeypatch, code, status, expected, backend_code
):
    backend_code = backend_code or code
    for key in ("SUPABASE_URL", "KIOKU_MCP_URL", "KIOKU_API_URL"):
        monkeypatch.setenv(key, "http://fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture")
    monkeypatch.setenv("MIHARI_TSUKAI_SERVICE_TOKEN", "fixture")
    spec = importlib.util.spec_from_file_location(
        "mihari_budget_fixture", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    admitted = []

    def response(body, status_code=200):
        return SimpleNamespace(
            json=lambda: body,
            status_code=status_code,
            ok=status_code < 400,
            raise_for_status=lambda: None,
        )

    def post(url, **kwargs):
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
            admitted.append(kwargs["json"])
            return response({"job_id": f"job-{len(admitted)}"})
        return response({"detail": f"maintenance execution: {backend_code}"}, 502)

    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(
        module.requests,
        "get",
        lambda *a, **kw: response({"status": status, "error": {"code": code}}),
    )
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match=f"maintenance execution: {backend_code}"):
        module.maintenance_post(
            "http://fixture/api/mihari/learnings",
            headers={},
            json={"folder_id": "folder"},
            timeout=120,
            _batches=1,
        )
    assert len(admitted) == expected


@pytest.mark.parametrize("repair,expected_admissions", [(False, 1), (True, 2)])
@pytest.mark.parametrize("operation", ["learnings", "reports"])
def test_failed_result_repair_preserves_validation_reason(
    monkeypatch, repair, expected_admissions, operation
):
    for key in ("SUPABASE_URL", "KIOKU_MCP_URL", "KIOKU_API_URL"):
        monkeypatch.setenv(key, "http://fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture")
    monkeypatch.setenv("MIHARI_TSUKAI_SERVICE_TOKEN", "fixture")
    spec = importlib.util.spec_from_file_location(
        "mihari_result_error", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    admissions, preparations = [], []

    def response(body, status=200):
        return SimpleNamespace(
            json=lambda: body, status_code=status, ok=status < 400, raise_for_status=lambda: None
        )

    def post(url, **kwargs):
        if url.endswith("/prepare"):
            preparations.append(kwargs["json"])
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
            admissions.append(kwargs["json"])
            return response({"job_id": "job"})
        return response({"detail": "invalid_result:unsupported learning commit"}, 409)

    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module.requests, "get", lambda *a, **kw: response({"status": "completed"}))
    with pytest.raises(
        RuntimeError, match="bounded repair: invalid_result:unsupported learning commit"
    ):
        module.maintenance_post(
            "http://fixture/api/mihari/" + operation,
            headers={},
            json={"folder_id": "folder"},
            timeout=120,
            _repair=repair,
            _batches=1,
        )
    assert len(admissions) == expected_admissions

    assert "retry_preparation_id" not in preparations[0]
    if repair and operation == "reports":
        assert preparations[1]["retry_preparation_id"] == "prep"
    elif repair:
        assert "retry_preparation_id" not in preparations[1]


def test_monthly_snapshot_finishes_without_restarting_at_thirty_seconds(monkeypatch):
    for key in ("SUPABASE_URL", "KIOKU_MCP_URL", "KIOKU_API_URL"):
        monkeypatch.setenv(key, "http://fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture")
    spec = importlib.util.spec_from_file_location(
        "mihari_monthly_fixture", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if kwargs["timeout"][1] < 32:
            raise module.requests.Timeout("Snapshot not yet prepared")
        return SimpleNamespace(
            json=lambda: {"engine": "skip", "updated": False},
            raise_for_status=lambda: None,
        )

    monkeypatch.setattr(module.requests, "post", post)
    result = module.maintenance_post(
        "http://fixture/api/mihari/reports", headers={}, json={"folder_id": "f1"}, timeout=180
    )
    assert result.status_code == 200
    assert calls == ["http://fixture/api/mihari/execution/prepare"]


def test_report_date_failure_uses_one_citation_only_job_after_budget_recovery(monkeypatch):
    for key in ("SUPABASE_URL", "KIOKU_MCP_URL", "KIOKU_API_URL"):
        monkeypatch.setenv(key, "http://fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture")
    monkeypatch.setenv("MIHARI_TSUKAI_SERVICE_TOKEN", "fixture")
    spec = importlib.util.spec_from_file_location(
        "mihari_quote_fixture", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    preparations, admissions, publications = [], [], []

    def response(body, status=200, headers=None):
        return SimpleNamespace(
            json=lambda: body,
            status_code=status,
            ok=status < 400,
            headers=headers or {},
            raise_for_status=lambda: None,
        )

    def post(url, **kwargs):
        if url.endswith("/prepare"):
            preparations.append(kwargs["json"])
            return response(
                {
                    "engine": "tsukai",
                    "url": "http://runner",
                    "capability": "cap",
                    "request": {},
                    "preparation_id": f"prep-{len(preparations)}",
                }
            )
        if url.endswith("/v1/jobs"):
            admissions.append(1)
            return response({"job_id": "job"})
        publications.append(1)
        if len(publications) == 1:
            return response({"detail": "maintenance execution: wall_timeout"}, 502)
        if len(publications) == 2:
            return response(
                {"detail": "invalid_result:Report quote date does not match its update"},
                409,
                {"X-Kioku-Report-Repair": "quotes"},
            )
        return response({"updated": True})

    def get(*args, **kwargs):
        return response(
            {"status": "failed", "error": {"code": "wall_timeout"}}
            if len(admissions) == 1
            else {"status": "completed"}
        )

    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module.requests, "get", get)
    assert module.maintenance_post(
        "http://fixture/api/mihari/reports", headers={}, json={"folder_id": "f1"}, timeout=180
    ).ok
    assert len(admissions) == 3
    assert preparations[1]["retry_preparation_id"] == "prep-1"
    assert preparations[2]["quote_repair_preparation_id"] == "prep-2"
    assert "retry_preparation_id" not in preparations[2]


@pytest.mark.parametrize("final_invalid", [False, True])
def test_unsupported_evidence_uses_at_most_one_remaining_full_review(monkeypatch, final_invalid):
    for key in ("SUPABASE_URL", "KIOKU_MCP_URL", "KIOKU_API_URL"):
        monkeypatch.setenv(key, "http://fixture")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture")
    monkeypatch.setenv("MIHARI_TSUKAI_SERVICE_TOKEN", "fixture")
    spec = importlib.util.spec_from_file_location(
        "mihari_quote_fallback", Path(__file__).parents[2] / "mihari/mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    preparations, publications = [], []

    def response(body, status=200, headers=None):
        return SimpleNamespace(
            json=lambda: body,
            status_code=status,
            ok=status < 400,
            headers=headers or {},
            raise_for_status=lambda: None,
        )

    def post(url, **kwargs):
        if url.endswith("/prepare"):
            preparations.append(kwargs["json"])
            return response(
                {
                    "engine": "tsukai",
                    "url": "http://runner",
                    "capability": "cap",
                    "request": {},
                    "preparation_id": f"prep-{len(preparations)}",
                }
            )
        if url.endswith("/v1/jobs"):
            return response({"job_id": "job"})
        publications.append(1)
        if len(publications) == 2:
            return response(
                {"detail": "invalid_result:Citation repair lacks an allowed supporting quote"}, 409
            )
        if len(publications) == 1 or final_invalid:
            return response(
                {"detail": "invalid_result:Report runtime claim requires observed evidence"},
                409,
                {"X-Kioku-Report-Repair": "quotes"},
            )
        return response({"updated": True})

    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(module.requests, "get", lambda *a, **kw: response({"status": "completed"}))

    def call():
        return module.maintenance_post(
            "http://fixture/api/mihari/reports", headers={}, json={"folder_id": "f1"}, timeout=180
        )

    if final_invalid:
        with pytest.raises(RuntimeError, match="bounded repair"):
            call()
    else:
        assert call().ok
    assert len(preparations) == 3
    assert preparations[1]["quote_repair_preparation_id"] == "prep-1"
    assert preparations[2]["retry_preparation_id"] == "prep-1"
    assert "quote_repair_preparation_id" not in preparations[2]
