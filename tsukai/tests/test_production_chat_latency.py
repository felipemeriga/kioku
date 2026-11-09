"""Transport doubles verify web parity, publication, and quota without inference."""

import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/benchmarks"))
spec = importlib.util.spec_from_file_location(
    "production_chat_latency", ROOT / "scripts/benchmarks/production_chat_latency.py"
)
latency = importlib.util.module_from_spec(spec)
spec.loader.exec_module(latency)


@pytest.mark.asyncio
async def test_exact_web_payload_replace_and_publication():
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/api/chat":
            payload = json.loads(request.content)
            assert payload == {
                "rebuild_from_committed_history": False,
                "conversation_id": "conversation",
                "turn_id": payload["turn_id"],
                "content": "Real user question",
                "model": "haiku",
                "mode": "agentic",
                "reasoning_effort": "low",
                "debug": False,
                "scope_folder_id": None,
                "scope_filename": None,
                "timezone": "America/Sao_Paulo",
            }
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    ': keepalive\n\ndata: {"token":"draft","job_id":"job"}\n\n'
                    'data: {"replace":"Final answer",\n'
                    'data: "done":true,"message_id":"message"}\n\n'
                ),
            )
        if request.url.path.startswith("/api/chat/turns/"):
            return httpx.Response(200, json={"assistant_message_id": "message"})
        return httpx.Response(
            200,
            json={"messages": [{"id": "message", "role": "assistant", "content": "Final answer"}]},
        )

    async with httpx.AsyncClient(
        base_url="https://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        row = await latency.measure_turn(
            client,
            "conversation",
            {
                "id": "real-1",
                "content": "Real user question",
            },
            resumed=False,
            admit=lambda: None,
        )
    assert row["success"] is True
    assert row["answer"] == "Final answer"
    assert row["first_visible_text_seconds"] <= row["complete_seconds"]
    assert row["verification_seconds"] >= row["complete_seconds"]
    assert len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        'data: {"token":"partial"}\n\n',
        'data: {"replace":"answer","done":true,"message_id":"wrong"}\n\n',
    ],
)
async def test_disconnect_or_unpublished_result_cannot_pass(body):
    posts = 0

    def handler(request):
        nonlocal posts
        if request.method == "POST":
            posts += 1
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)
        return httpx.Response(200, json={"messages": [], "assistant_message_id": None})

    async with httpx.AsyncClient(
        base_url="https://example.test", transport=httpx.MockTransport(handler)
    ) as client:
        row = await latency.measure_turn(
            client,
            "conversation",
            {
                "id": "real-1",
                "content": "Question",
            },
            resumed=False,
            admit=lambda: None,
        )
    assert row["success"] is False
    assert row["error"]
    assert posts == 1


@pytest.mark.asyncio
async def test_revoked_lease_blocks_resumed_model_call():
    async with httpx.AsyncClient(base_url="https://example.test") as client:
        row = await latency.measure_turn(
            client,
            "conversation",
            {
                "id": "real-2",
                "content": "Follow up",
            },
            resumed=True,
            admit=lambda: "usage_reserve_reached",
        )
    assert row["error"] == "usage_reserve_reached"
    assert row["frames"] == []


def test_forbids_original_conversation_and_invalid_input():
    with pytest.raises(ValueError, match="existing chats are forbidden"):
        latency.validate_manifest(
            {
                "conversations": [
                    {
                        "conversation_id": "original",
                        "turns": [{"id": "x", "content": "q"}],
                    }
                ]
            }
        )
    with pytest.raises(ValueError, match="Duplicate"):
        latency.validate_manifest(
            {
                "conversations": [
                    {
                        "turns": [
                            {"id": "x", "content": "q"},
                            {"id": "x", "content": "q"},
                        ]
                    }
                ]
            }
        )


@pytest.mark.asyncio
async def test_full_runner_fresh_then_resume_private_artifacts(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(
        json.dumps({"access_token": "PRIVATE_TOKEN", "api_base": "https://test.invalid"})
    )
    lease = tmp_path / "lease.json"
    lease.write_text(
        json.dumps(
            {
                "five_hour": 0,
                "seven_day": 0,
                "observed_at": time.time(),
                "account_verified": True,
            }
        )
    )
    proof = tmp_path / "proof.json"
    proof.write_text('{"backend_revision":"production"}')
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "conversations": [
                    {
                        "id": "real",
                        "turns": [
                            {"id": "one", "content": "First"},
                            {"id": "two", "content": "Follow up"},
                        ],
                    }
                ]
            }
        )
    )
    output = tmp_path / "output"
    turn = {}
    messages = []

    def handler(request):
        if request.url.path == "/api/chat/models":
            return httpx.Response(200, json={})
        if request.url.path == "/api/conversations" and request.method == "POST":
            return httpx.Response(200, json={"id": "benchmark-only"})
        if request.method == "PATCH":
            assert json.loads(request.content)["title"].startswith("[Latency benchmark]")
            return httpx.Response(200, json={})
        if request.url.path == "/api/chat":
            payload = json.loads(request.content)
            message_id = f"message-{len(messages)}"
            turn[payload["turn_id"]] = message_id
            messages.append({"id": message_id, "role": "assistant", "content": "answer"})
            frame = {"replace": "answer", "done": True, "message_id": message_id}
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=f"data: {json.dumps(frame)}\n\n",
            )
        if request.url.path.startswith("/api/chat/turns/"):
            return httpx.Response(
                200, json={"assistant_message_id": turn[request.url.path.rsplit("/", 1)[1]]}
            )
        return httpx.Response(200, json={"messages": messages})

    summary = await latency.run(
        SimpleNamespace(
            auth=auth,
            manifest=manifest,
            usage_lease=lease,
            deployment_proof=proof,
            output=output,
            workers=4,
        ),
        transport=httpx.MockTransport(handler),
    )
    assert summary["successful"] == 2
    rows = [json.loads(path.read_text()) for path in sorted(output.glob("case-*.json"))]
    assert [row["context"] for row in rows] == ["fresh", "resumed"]
    for artifact in output.iterdir():
        assert artifact.stat().st_mode & 0o777 == 0o600
        assert "PRIVATE_TOKEN" not in artifact.read_text()
