"""Real HTTP disconnect/replay, same-conversation exclusion, cancel and rebuild.

Uses the private config for tsukai_http_acceptance.py. Makes real native model
calls, so run only after the integrating operator declares runtime readiness.
Synthetic conversations and accounting records are preserved for later cleanup.
"""

import argparse
import json
import logging
import stat
import time
import uuid
from pathlib import Path

import httpx

from tsukai_http_acceptance import CheckFailure, save


def frames(response):
    response.raise_for_status()
    for line in response.iter_lines():
        if line.startswith("data: "):
            frame = json.loads(line[6:])
            if frame.get("error"):
                raise CheckFailure("Lifecycle stream emitted a native error")
            yield frame


def body(config, conversation, content, rebuild=False):
    return {
        "conversation_id": conversation,
        "turn_id": str(uuid.uuid4()),
        "scope_folder_id": config["folder_id"],
        "model": "haiku",
        "mode": "agentic",
        "debug": True,
        "content": content,
        "rebuild_from_committed_history": rebuild,
    }


def conversation(client, config, label):
    response = client.post("/api/conversations")
    response.raise_for_status()
    identifier = response.json()["id"]
    response = client.patch(
        f"/api/conversations/{identifier}",
        json={"title": config["fixture_name"] + " " + label},
    )
    response.raise_for_status()
    return identifier


def terminal(client, request):
    result = None
    deltas = 0
    with client.stream("POST", "/api/chat", json=request) as response:
        for frame in frames(response):
            deltas += bool(frame.get("token"))
            if frame.get("done"):
                result = frame
    if not result or not result.get("message_id"):
        raise CheckFailure("Lifecycle stream has no durable terminal message")
    return result, deltas


def reconnect(client, config):
    identifier = conversation(client, config, "disconnect-replay")
    marker = "reconnect-" + uuid.uuid4().hex[:12]
    request = body(
        config,
        identifier,
        f"Reply with {marker} and a short sentence confirming this synthetic test.",
    )
    job = None
    cursor = 0
    with client.stream("POST", "/api/chat", json=request) as response:
        for frame in frames(response):
            job = frame.get("job_id", job)
            cursor = frame.get("event_id", cursor)
            if (frame.get("progress") or {}).get("type") == "attempt.started":
                break
            if frame.get("done"):
                raise CheckFailure(
                    "Disconnect probe did not detach during actual execution"
                )
    if not job or not cursor:
        raise CheckFailure("Disconnect probe lacks actual active attempt cursor")
    final = None
    sequences = []
    deltas = 0
    with client.stream(
        "GET", f"/api/chat/jobs/{job}/events", params={"after": cursor}
    ) as response:
        for frame in frames(response):
            if frame.get("event_id") is not None:
                sequences.append(frame["event_id"])
            deltas += bool(frame.get("token"))
            if frame.get("done"):
                final = frame
    if not final or marker not in final.get("replace", "") or not deltas:
        raise CheckFailure("Reconnect did not recover the actual streamed answer")
    if any(sequence <= cursor for sequence in sequences) or sequences != sorted(
        set(sequences)
    ):
        raise CheckFailure(
            "Reconnect replay repeated or reordered durable event sequence"
        )
    replay, _ = terminal(client, request)
    if replay["job_id"] != job or replay["message_id"] != final["message_id"]:
        raise CheckFailure("Stable-turn replay started a different job or message")
    response = client.get(f"/api/conversations/{identifier}")
    response.raise_for_status()
    messages = response.json()["messages"]
    if len(messages) != 2 or sum(m["id"] == final["message_id"] for m in messages) != 1:
        raise CheckFailure("Disconnect/retry duplicated durable conversation messages")
    return {
        "case": "disconnect_reconnect_idempotency",
        "conversation_id": identifier,
        "turn_id": request["turn_id"],
        "job_id": job,
        "cursor": cursor,
        "replayed_event_count": len(sequences),
        "delta_frames": deltas,
        "message_id": final["message_id"],
        "message_count": len(messages),
    }


def cancel_rebuild(client, config):
    identifier = conversation(client, config, "concurrency-cancel-rebuild")
    request = body(
        config,
        identifier,
        "Explain in 60 words how this synthetic acceptance test checks safe cancellation.",
    )
    job = None
    with client.stream("POST", "/api/chat", json=request) as response:
        for frame in frames(response):
            job = frame.get("job_id", job)
            if (frame.get("progress") or {}).get("type") == "attempt.started":
                competing = body(
                    config,
                    identifier,
                    "This competing turn must be rejected while another turn is active.",
                )
                conflict = client.post("/api/chat", json=competing)
                if conflict.status_code != 409:
                    raise CheckFailure(
                        "Same-conversation concurrent turn was not rejected with409"
                    )
                cancelled = client.post(f"/api/chat/turns/{request['turn_id']}/cancel")
                cancelled.raise_for_status()
                break
            if frame.get("done"):
                raise CheckFailure(
                    "Cancellation probe missed the actual running attempt"
                )
    if not job:
        raise CheckFailure("Cancellation probe has no actual native job")
    deadline = time.monotonic() + 90
    state = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/chat/turns/{request['turn_id']}")
        response.raise_for_status()
        state = response.json()["state"]
        if state in {"cancelled", "failed", "uncertain", "committed", "acknowledged"}:
            break
        time.sleep(1)
    if state != "cancelled":
        raise CheckFailure("Actual running native job did not reach cancelled state")
    marker = "rebuilt-" + uuid.uuid4().hex[:12]
    restored = body(config, identifier, f"Reply exactly with {marker}.", rebuild=True)
    final, deltas = terminal(client, restored)
    if marker not in final.get("replace", "") or not deltas:
        raise CheckFailure("Explicit post-cancel rebuild did not stream the new answer")
    return {
        "case": "same_conversation_cancel_rebuild",
        "conversation_id": identifier,
        "cancelled_turn_id": request["turn_id"],
        "cancelled_job_id": job,
        "cancelled_state": state,
        "concurrent_status": 409,
        "rebuilt_turn_id": restored["turn_id"],
        "rebuilt_job_id": final["job_id"],
        "rebuilt_message_id": final["message_id"],
        "delta_frames": deltas,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--case", choices=("reconnect", "cancel-rebuild"), required=True
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    config = json.loads(args.config.read_text())
    token = Path(config["token_file"])
    if (
        not config["fixture_name"].startswith("tsukai-e2e-")
        or stat.S_IMODE(token.stat().st_mode) != 0o600
    ):
        raise SystemExit("Private token and isolated fixture required")
    began = time.monotonic()
    try:
        with httpx.Client(
            base_url=config["url"],
            headers={"Authorization": "Bearer " + token.read_text().strip()},
            timeout=httpx.Timeout(180, connect=20),
        ) as client:
            result = (
                reconnect(client, config)
                if args.case == "reconnect"
                else cancel_rebuild(client, config)
            )
        record = {
            "ok": True,
            "kind": "real_http_lifecycle",
            "elapsed_seconds": time.monotonic() - began,
            **result,
        }
    except Exception as exc:
        record = {
            "ok": False,
            "kind": "real_http_lifecycle",
            "case": args.case,
            "reason": str(exc) if isinstance(exc, CheckFailure) else type(exc).__name__,
        }
        if isinstance(exc, httpx.HTTPStatusError):
            record["http_status"] = exc.response.status_code
    save(config["evidence"], record, append=True)
    print(json.dumps(record, sort_keys=True))
    if not record["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
