"""Real HTTP disconnect/replay, same-conversation exclusion, cancel and rebuild.

Uses the private config for tsukai_http_acceptance.py. Makes real native model
calls, so run only after the integrating operator declares runtime readiness.
Synthetic conversations and accounting records are preserved for later cleanup.
"""

import argparse
import hashlib
import json
import logging
import re
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
                identities = []
                for key in ("job_id", "turn_id"):
                    try:
                        identities.append(
                            key + "=" + str(uuid.UUID(str(frame.get(key))))
                        )
                    except ValueError:
                        pass
                digest = hashlib.sha256(
                    json.dumps(frame["error"], sort_keys=True).encode()
                ).hexdigest()
                raise CheckFailure(
                    "Lifecycle stream emitted a native error; "
                    + "; ".join(identities)
                    + "; error_sha256="
                    + digest
                )
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
    save(
        config["evidence"],
        {
            "kind": "fixture_created",
            "conversation_id": identifier,
            "fixture_name": config["fixture_name"],
            "case": label,
        },
        append=True,
    )
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
    deadline = time.monotonic() + 30
    acknowledged = False
    while time.monotonic() < deadline:
        state_response = client.get(f"/api/chat/turns/{request['turn_id']}")
        state_response.raise_for_status()
        if state_response.json()["state"] == "acknowledged":
            acknowledged = True
            break
        time.sleep(1)
    if not acknowledged:
        raise CheckFailure(
            "Disconnect probe did not durably acknowledge before idempotent replay"
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
        "acknowledged_before_retry": acknowledged,
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
        raise CheckFailure(
            "Actual native cancellation ended in state="
            + str(state)
            + "; turn_id="
            + request["turn_id"]
            + "; job_id="
            + str(job)
        )
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


def policy_switch(client, config):
    state = json.loads(Path(config["state"]).read_text())
    fixture = state["conversations"]["haiku-agentic"]
    identifier, marker = fixture["id"], fixture["nonce"]
    changed = body(
        config,
        identifier,
        "What acceptance code did I ask you to remember? Reply only with that code.",
    )
    changed.update({"model": "sonnet", "mode": "deep"})
    rejected = False
    status = None
    try:
        with client.stream("POST", "/api/chat", json=changed) as response:
            status = response.status_code
            if status == 409:
                rejected = True
            elif status == 200:
                for line in response.iter_lines():
                    if line.startswith("data: "):
                        frame = json.loads(line[6:])
                        if frame.get("error"):
                            rejected = True
                        if frame.get("done") and not frame.get("error"):
                            raise CheckFailure(
                                "Changed policy silently resumed without explicit rebuild"
                            )
            else:
                response.raise_for_status()
    except httpx.RemoteProtocolError:
        # Admission may terminate the initial SSE before a job frame. Its
        # durable turn state must still explain the controlled rejection.
        pass
    response = client.get(f"/api/chat/turns/{changed['turn_id']}")
    response.raise_for_status()
    denied = response.json()
    if denied.get("state") == "failed" and denied.get("error_code") in {
        "admission_rejected",
        "conversation_policy_changed",
        "conversation_needs_rebuild",
    }:
        rejected = True
    if not rejected:
        raise CheckFailure(
            "Model/mode switch did not expose controlled policy rejection"
        )
    rebuilt = {
        **changed,
        "turn_id": str(uuid.uuid4()),
        "rebuild_from_committed_history": True,
    }
    final, deltas = terminal(client, rebuilt)
    if marker not in final.get("replace", "") or not deltas:
        raise CheckFailure(
            "Haiku-agentic to Sonnet-deep rebuild lost committed conversation history"
        )
    usage = ((final.get("debug") or {}).get("execution") or {}).get("usage") or {}
    if not any("sonnet" in model.lower() for model in usage.get("model_usage", {})):
        raise CheckFailure(
            "Policy rebuild has no actual Sonnet model usage attribution"
        )
    return {
        "case": "same_conversation_model_mode_switch",
        "conversation_id": identifier,
        "from_model": "haiku",
        "from_mode": "agentic",
        "to_model": "sonnet",
        "to_mode": "deep",
        "rejected_turn_id": changed["turn_id"],
        "initial_http_status": status,
        "rejected_state": denied.get("state"),
        "rejected_error_code": denied.get("error_code"),
        "rebuild_explicit": True,
        "rebuilt_turn_id": rebuilt["turn_id"],
        "job_id": final["job_id"],
        "message_id": final["message_id"],
        "delta_frames": deltas,
        "history_preserved": True,
        "usage": usage,
    }


def web_search(client, config):
    identifier = conversation(client, config, "public-web-search")
    query = "site:docs.python.org/3/tutorial/ official Python tutorial"
    request = body(
        config,
        identifier,
        "Use web_search exactly once with this exact public query: "
        + json.dumps(query)
        + ". Summarize what the official Python tutorial teaches in one sentence "
        "and include its direct official source link. Send no fixture content or identifiers to search.",
    )
    final, deltas = terminal(client, request)
    tools = (final.get("debug") or {}).get("tool_calls") or []
    web = [tool for tool in tools if tool.get("name") == "web_search"]
    if len(web) != 1 or web[0].get("is_error") or not deltas:
        raise CheckFailure("Actual web-search call/streaming gate failed")
    artifact_id = web[0].get("artifact_id")
    if not artifact_id:
        raise CheckFailure("Actual web-search result artifact missing")
    offset, parts, trace = 0, [], {}
    while True:
        response = client.get(
            f"/api/chat/jobs/{final['job_id']}/artifacts/{artifact_id}",
            params={"offset": offset, "limit": 16384},
        )
        response.raise_for_status()
        artifact = response.json()
        parts.append(artifact["result"])
        trace = artifact["trace"]
        if artifact.get("next_offset") is None:
            break
        offset = artifact["next_offset"]
        if offset > 100000:
            raise CheckFailure("Synthetic public web result exceeds probe bound")
    actual_query = trace.get("query") or (trace.get("input") or {}).get("query")
    if actual_query != query:
        raise CheckFailure("Web tool query differs from approved fixed public query")
    visible = "".join(parts)
    answer_links = [
        link.rstrip(".,;:")
        for link in re.findall(
            r"https://docs\.python\.org/[^\s)\]<>]+", final["replace"]
        )
    ]
    supported_links = [link for link in answer_links if link in visible]
    if not supported_links:
        raise CheckFailure(
            "Web answer has no actual official-source link supported by tool artifact"
        )
    return {
        "case": "public_web_search",
        "conversation_id": identifier,
        "turn_id": request["turn_id"],
        "job_id": final["job_id"],
        "message_id": final["message_id"],
        "delta_frames": deltas,
        "artifact_id": artifact_id,
        "artifact_characters": len(visible),
        "artifact_sha256": hashlib.sha256(visible.encode()).hexdigest(),
        "public_query": actual_query,
        "verified_official_links": supported_links,
        "numbered_citations": len(final.get("citations") or []),
        "citation_type": "verified inline official URL",
    }


def restart_recall(client, config):
    path = Path(config["state"]).parent / "restart-recall-plan.json"
    seed = json.loads(path.read_text())
    request = body(
        config,
        seed["conversation_id"],
        "What acceptance code did I ask you to remember? Reply only with that code.",
    )
    request.update(
        {
            "model": seed["model"],
            "mode": seed["mode"],
            "scope_filename": seed["scope_filename"],
            "rebuild_from_committed_history": False,
        }
    )
    final, deltas = terminal(client, request)
    if seed["nonce"] not in final.get("replace", "") or not deltas:
        raise CheckFailure(
            "Same-image restart recall lost the committed seeded nonce or streaming"
        )
    execution = (final.get("debug") or {}).get("execution") or {}
    usage = execution.get("usage") or {}
    if "resume" not in usage.get("attribution", ""):
        raise CheckFailure("Post-restart job has no actual native resume attribution")
    return {
        "case": "same_image_restart_recall",
        "conversation_id": seed["conversation_id"],
        "turn_id": request["turn_id"],
        "job_id": final["job_id"],
        "message_id": final["message_id"],
        "delta_frames": deltas,
        "rebuild_from_committed_history": False,
        "nonce_sha256": seed["nonce_sha256"],
        "prior_message_id": seed["last_assistant_message_id"],
        "native_resume_attribution": usage["attribution"],
        "attempt_timings": execution.get("timings"),
        "usage": usage,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--case",
        choices=(
            "reconnect",
            "cancel-rebuild",
            "policy-switch",
            "web-search",
            "restart-recall",
        ),
        required=True,
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
            action = {
                "reconnect": reconnect,
                "cancel-rebuild": cancel_rebuild,
                "policy-switch": policy_switch,
                "web-search": web_search,
                "restart-recall": restart_recall,
            }[args.case]
            result = action(client, config)
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
