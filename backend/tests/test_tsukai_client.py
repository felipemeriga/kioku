import json

import httpx
import pytest

from services.ai.client import ExecutionError, TsukaiClient
from services.ai.registry import engine_for


def frame(seq, kind="text.delta", job="job"):
    return "data: " + json.dumps({"job_id": job, "seq": seq, "type": kind, "data": {}}) + "\n\n"


def test_reconnect_deduplicates_and_uses_last_durable_cursor():
    cursors = []

    def handler(request):
        cursors.append(request.headers["Last-Event-ID"])
        return httpx.Response(
            200,
            text=frame(1) if len(cursors) == 1 else frame(1) + frame(2, "job.completed"),
        )

    client = TsukaiClient(
        "http://tsukai", "service", "grant", transport=httpx.MockTransport(handler)
    )
    assert [event["seq"] for event in client.events("job")] == [1, 2]
    assert cursors == ["0", "1"]
    client.close()


@pytest.mark.parametrize(
    "body,code", [(frame(2), "event_gap"), (frame(1, job="foreign"), "foreign_event")]
)
def test_rejects_corrupt_stream(body, code):
    client = TsukaiClient(
        "http://tsukai",
        "s",
        "g",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)),
    )
    with pytest.raises(ExecutionError, match=code):
        list(client.events("job", reconnects=0))
    client.close()


def test_eof_without_terminal_fails():
    client = TsukaiClient(
        "http://tsukai",
        "s",
        "g",
        transport=httpx.MockTransport(lambda request: httpx.Response(200, text=frame(1))),
    )
    with pytest.raises(ExecutionError, match="missing_terminal"):
        list(client.events("job", reconnects=0))
    client.close()


def test_default_api_and_owner_only_explicit_native(monkeypatch):
    monkeypatch.delenv("TSUKAI_NATIVE_TASKS", raising=False)
    assert engine_for("query_rewrite", "owner") == "api"
    monkeypatch.setenv("TSUKAI_NATIVE_TASKS", "query_rewrite,image_ocr")
    monkeypatch.setenv("TSUKAI_CREDENTIAL_OWNER_ID", "owner")
    assert engine_for("query_rewrite", "foreign") == "api"
    with pytest.raises(PermissionError):
        engine_for("query_rewrite", "foreign", explicit_native=True)
    assert engine_for("query_rewrite", "owner") == "tsukai"
    with pytest.raises(ValueError, match="unverified"):
        engine_for("image_ocr", "owner")


def test_expired_replay_fetches_canonical_result_without_new_inference():
    methods = []

    def handler(request):
        methods.append((request.method, request.url.path))
        if request.url.path.endswith("events"):
            return httpx.Response(410)
        return httpx.Response(
            200,
            json={
                "job_id": "job",
                "status": "completed",
                "result": {"text": "canonical"},
            },
        )

    client = TsukaiClient("http://tsukai", "s", "g", transport=httpx.MockTransport(handler))
    events = list(client.events("job", cursor=99))
    assert events[0]["type"] == "replay.expired"
    assert events[0]["data"]["result"]["text"] == "canonical"
    assert all(method == "GET" for method, _ in methods)
    client.close()


@pytest.mark.parametrize("outcome", ["needs_input", "failed"])
def test_nonpublishable_structured_outcomes_fail(outcome):
    client = TsukaiClient(
        "http://tsukai",
        "s",
        "g",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "job_id": "job",
                    "status": "completed",
                    "result": {
                        "text": "question",
                        "structured": {
                            "outcome": outcome,
                            "data": None,
                        },
                    },
                },
            )
        ),
    )
    with pytest.raises(ExecutionError, match=outcome):
        client.result("job")
    client.close()


def test_completion_event_pair_uses_one_authenticated_http_request():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"accepted": True})

    client = TsukaiClient(
        "http://tsukai", "service", "grant", transport=httpx.MockTransport(handler)
    )
    try:
        client.tool_events(
            "job",
            "attempt",
            [
                ("retrieval.completed", {"result_ref": "artifact"}),
                ("tool.completed", {"result_ref": "artifact"}),
            ],
        )
    finally:
        client.close()
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/jobs/job/tool-events/batch"
    assert requests[0].headers["Authorization"] == "Bearer service"
    assert requests[0].headers["X-Tsukai-Capability"] == "grant"
    value = json.loads(requests[0].content)
    assert value["attempt_id"] == "attempt"
    assert [item["type"] for item in value["events"]] == ["retrieval.completed", "tool.completed"]


def test_batch_unknown_route_only_uses_the_existing_durable_event_protocol():
    paths = []
    kinds = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/batch"):
            return httpx.Response(404, json={"detail": "Not Found"})
        kinds.append(json.loads(request.content)["type"])
        return httpx.Response(200, json={"accepted": True})

    client = TsukaiClient(
        "http://tsukai", "service", "grant", transport=httpx.MockTransport(handler)
    )
    try:
        client.tool_events("job", "attempt", [("retrieval.completed", {}), ("tool.completed", {})])
    finally:
        client.close()
    assert paths == [
        "/v1/jobs/job/tool-events/batch",
        "/v1/jobs/job/tool-events",
        "/v1/jobs/job/tool-events",
    ]
    assert kinds == ["retrieval.completed", "tool.completed"]


@pytest.mark.parametrize("failure", ["timeout", "transport", "domain404", "non_json404", 403, 503])
def test_batch_never_replays_after_uncertainty_or_domain_rejection(failure):
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if failure == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if failure == "transport":
            raise httpx.ConnectError("fixture transport failure", request=request)
        if failure == "domain404":
            return httpx.Response(404, json={"detail": "job_not_found"})
        if failure == "non_json404":
            return httpx.Response(404, text="Not Found")
        return httpx.Response(failure, json={"detail": "rejected"})

    client = TsukaiClient(
        "http://tsukai", "service", "grant", transport=httpx.MockTransport(handler)
    )
    try:
        with pytest.raises((httpx.HTTPStatusError, httpx.TransportError)):
            client.tool_events(
                "job", "attempt", [("retrieval.completed", {}), ("tool.completed", {})]
            )
    finally:
        client.close()
    assert paths == ["/v1/jobs/job/tool-events/batch"]
