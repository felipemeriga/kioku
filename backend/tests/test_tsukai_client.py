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
    with pytest.raises(PermissionError):
        engine_for("query_rewrite", "foreign")
    assert engine_for("query_rewrite", "owner") == "tsukai"
    with pytest.raises(ValueError, match="unverified"):
        engine_for("image_ocr", "owner")
