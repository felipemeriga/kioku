"""Real deployed HTTP chat probe with persisted conversation/turn evidence.

Private config fields: url, token_file (0600), folder_id, fixture_name
(tsukai-e2e-*), evidence, state. Optional seed_question and require_citations
exercise retrieval against a caller-provisioned fixture. This script creates
only self-owned synthetic conversations and preserves usage/history for review.
Run repeatedly to alternate fresh seed and stateful recall across six
model/mode combinations. It does not substitute for actual UI acceptance.
"""

import argparse
import datetime
import hashlib
import json
import logging
import os
import re
import stat
import time
import uuid
from pathlib import Path

import httpx


class CheckFailure(RuntimeError):
    """A sanitized acceptance assertion with no service response body."""


def save(path, value, append=False):
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC), 0o600
    )
    with os.fdopen(descriptor, "a" if append else "w") as stream:
        stream.write(json.dumps(value, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def probe(config, read_only=False):
    if not config["fixture_name"].startswith("tsukai-e2e-"):
        raise ValueError("Isolated tsukai-e2e-* fixture required")
    token_path = Path(config["token_file"])
    if stat.S_IMODE(token_path.stat().st_mode) != 0o600:
        raise ValueError("Token file must be mode 0600")
    state_path = Path(config["state"])
    state = (
        json.loads(state_path.read_text())
        if state_path.exists()
        else {"cycle": 0, "conversations": {}}
    )
    combinations = [
        (model, mode) for model in ("haiku", "sonnet") for mode in ("plain", "agentic", "deep")
    ]
    model, mode = combinations[(state["cycle"] // 2) % len(combinations)]
    key = f"{model}-{mode}"
    seed = state["cycle"] % 2 == 0
    with httpx.Client(
        base_url=config["url"].rstrip("/"),
        headers={"Authorization": "Bearer " + token_path.read_text().strip()},
        timeout=httpx.Timeout(180, connect=20),
    ) as client:
        if read_only:
            now = datetime.datetime.now(datetime.timezone.utc)
            paths = [
                ("folders", "/api/folders", {}),
                ("documents", "/api/documents", {"folder_id": config["folder_id"]}),
                ("conversations", "/api/conversations", {}),
                ("breadcrumbs", f"/api/folders/{config['folder_id']}/breadcrumbs", {}),
                ("learnings", f"/api/folders/{config['folder_id']}/learnings", {}),
                (
                    "learning_days",
                    f"/api/folders/{config['folder_id']}/learning-days",
                    {
                        "year": now.year,
                        "month": now.month,
                        "timezone": "America/Sao_Paulo",
                    },
                ),
                ("active_sessions", "/api/usage/native/active-sessions", {}),
            ]
            if config.get("journal_folder_id"):
                existing = config["journal_folder_id"]
                paths.extend(
                    [
                        (
                            "existing_learnings",
                            f"/api/folders/{existing}/learnings",
                            {},
                        ),
                        (
                            "existing_calendar",
                            f"/api/folders/{existing}/learning-days",
                            {
                                "year": config["journal_year"],
                                "month": config["journal_month"],
                                "timezone": "America/Sao_Paulo",
                            },
                        ),
                    ]
                )
            checks = []
            for name, path, params in paths:
                began = time.monotonic()
                response = client.get(path, params=params)
                response.raise_for_status()
                data = response.json()
                if name == "active_sessions" and data.get("available") is not True:
                    raise CheckFailure("Native admin telemetry is unavailable")
                if name in {"learning_days", "existing_calendar"} and not isinstance(
                    data.get("days"), list
                ):
                    raise CheckFailure("Learning calendar response has wrong shape")
                if name == "existing_calendar" and not data["days"]:
                    raise CheckFailure("Known nonempty existing journal calendar returned no days")
                checks.append(
                    {
                        "name": name,
                        "seconds": time.monotonic() - began,
                        "status": response.status_code,
                        "item_count": len(data)
                        if isinstance(data, list)
                        else len(data.get("days", data.get("learnings", data.get("sessions", [])))),
                        "sha256": hashlib.sha256(
                            json.dumps(data, sort_keys=True).encode()
                        ).hexdigest(),
                    }
                )
            result = {"kind": "real_http_read_only", "checks": checks}
            save(config["evidence"], result, append=True)
            return result
        if seed and not state.get("pending"):
            response = client.post("/api/conversations")
            response.raise_for_status()
            conversation = response.json()["id"]
            nonce = "tsukai-e2e-" + uuid.uuid4().hex[:12]
            state["conversations"][key] = {
                "id": conversation,
                "nonce": nonce,
                "filename": config.get("scope_filename"),
            }
            response = client.patch(
                f"/api/conversations/{conversation}",
                json={"title": config["fixture_name"] + " " + key},
            )
            response.raise_for_status()
            save(
                config["evidence"],
                {
                    "kind": "fixture_created",
                    "conversation_id": conversation,
                    "fixture_name": config["fixture_name"],
                    "model": model,
                    "mode": mode,
                },
                append=True,
            )
            save(state_path, state)
        fixture = state["conversations"][key]
        conversation, nonce = fixture["id"], fixture["nonce"]
        turn = state.get("pending", {}).get("turn_id") or str(uuid.uuid4())
        content = (
            (
                f"Remember this acceptance code: {nonce}. Include it in your answer. "
                + config.get("seed_question", "Reply briefly with the acceptance code.")
            )
            if seed
            else ("What acceptance code did I ask you to remember? Reply only with that code.")
        )
        long_sample = state["cycle"] == 2 and not state.get("long_sample_done")
        if long_sample:
            content += (
                " For this one streaming sample, write at least 150 words explaining your answer."
            )
        body = {
            "conversation_id": conversation,
            "turn_id": turn,
            "content": content,
            "model": model,
            "mode": mode,
            "debug": True,
            "scope_folder_id": config["folder_id"],
            "scope_filename": fixture.get("filename"),
        }
        state["pending"] = {"turn_id": turn}
        save(state_path, state)
        began = time.monotonic()
        terminal = None
        progress = set()
        token_count = 0
        first_token = None
        admin_observation = None
        admin_checks = 0
        with client.stream("POST", "/api/chat", json=body) as response:
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", ""):
                raise CheckFailure("Actual chat response is not SSE")
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                frame = json.loads(line[6:])
                if frame.get("error"):
                    # Never print service errors: they may include private text.
                    raise CheckFailure("Actual native chat emitted an error frame")
                if frame.get("stage"):
                    progress.add(frame["stage"])
                if (
                    long_sample
                    and admin_observation is None
                    and admin_checks < 3
                    and (
                        (frame.get("progress") or {}).get("type") == "attempt.started"
                        or frame.get("token")
                    )
                ):
                    admin_checks += 1
                    telemetry = client.get("/api/usage/native/active-sessions")
                    telemetry.raise_for_status()
                    active = telemetry.json()
                    matched = [
                        session
                        for session in active.get("sessions", [])
                        if session.get("job_id") == frame.get("job_id")
                    ]
                    if active.get("available") and matched:
                        admin_observation = {
                            key: matched[0].get(key)
                            for key in (
                                "job_id",
                                "attempt_id",
                                "state",
                                "pid",
                                "elapsed_seconds",
                                "native_cli_version",
                                "model_requested",
                            )
                        }
                if frame.get("token"):
                    token_count += 1
                    if first_token is None:
                        first_token = time.monotonic() - began
                if frame.get("done"):
                    terminal = frame
        if (
            not terminal
            or not terminal.get("message_id")
            or nonce not in terminal.get("replace", "")
        ):
            raise CheckFailure("Missing durable terminal answer or incorrect stateful recall")
        if token_count == 0:
            raise CheckFailure("Chat returned terminal-only output without streamed delta frames")
        if long_sample and (len(terminal["replace"].split()) <= 100 or token_count < 2):
            raise CheckFailure("Long streaming sample lacks >100 words and separate delta frames")
        if long_sample and admin_observation is None:
            raise CheckFailure("Admin telemetry never observed the actual active native job")
        execution = (terminal.get("debug") or {}).get("execution") or {}
        if execution.get("turn_id") != turn or not execution.get("timings"):
            raise CheckFailure("Native debug identity/timings missing")
        attempt_timings = execution["timings"].get("attempts") or []
        if not attempt_timings or any(
            not attempt.get("attempt_id")
            or not attempt.get("started_at")
            or not attempt.get("finished_at")
            or not isinstance(attempt.get("elapsed_seconds"), (int, float))
            or attempt["elapsed_seconds"] < 0
            for attempt in attempt_timings
        ):
            raise CheckFailure("Debug lacks measured durable per-attempt timing evidence")
        if config.get("require_citations") and seed and not terminal.get("citations"):
            raise CheckFailure("Fixture retrieval answer has no citations")
        artifacts = []
        if seed and mode != "plain" and config.get("expected_marker"):
            for tool in (terminal.get("debug") or {}).get("tool_calls") or []:
                if not tool.get("artifact_id"):
                    continue
                offset, chunks, trace = 0, [], {}
                while True:
                    artifact_response = client.get(
                        f"/api/chat/jobs/{terminal['job_id']}/artifacts/{tool['artifact_id']}",
                        params={"offset": offset, "limit": 16384},
                    )
                    artifact_response.raise_for_status()
                    artifact = artifact_response.json()
                    chunks.append(artifact["result"])
                    trace = artifact["trace"]
                    if artifact.get("next_offset") is None:
                        break
                    offset = artifact["next_offset"]
                    if offset > 200000:
                        raise CheckFailure("Synthetic tool artifact unexpectedly exceeds bound")
                visible = "".join(chunks)
                scope = trace.get("effective_scope") or {}
                if (
                    scope.get("folder_ids") != [config["folder_id"]]
                    or scope.get("filename") != body["scope_filename"]
                ):
                    raise CheckFailure(
                        "Actual debug artifact effective scope differs from fixture filter"
                    )
                sources = trace.get("sources") or []
                artifacts.append(
                    {
                        "artifact_id": tool["artifact_id"],
                        "name": tool.get("name"),
                        "marker_present": config["expected_marker"] in visible,
                        "result_sha256": hashlib.sha256(visible.encode()).hexdigest(),
                        "characters": len(visible),
                        "scope_folder_ids": scope["folder_ids"],
                        "scope_filename": scope.get("filename"),
                        "sources": [
                            {
                                key: source.get(key)
                                for key in (
                                    "citation_number",
                                    "source",
                                    "source_id",
                                    "source_type",
                                    "folder_id",
                                    "date",
                                    "last_updated",
                                )
                            }
                            | {
                                "revision_id": (source.get("metadata") or {}).get("revision_id"),
                                "snapshot_availability": (source.get("metadata") or {}).get(
                                    "snapshot_availability"
                                ),
                            }
                            for source in sources
                        ],
                    }
                )
            if not any(
                a["marker_present"]
                and any(
                    s.get("source") == config.get("expected_source_filename")
                    and s.get("folder_id") == config["folder_id"]
                    for s in a["sources"]
                )
                for a in artifacts
            ):
                raise CheckFailure(
                    "Actual full debug artifacts lack marker and scoped source provenance"
                )
        response = client.get(f"/api/conversations/{conversation}")
        response.raise_for_status()
        messages = response.json()["messages"]
        saved = [message for message in messages if message["id"] == terminal["message_id"]]
        if len(saved) != 1 or nonce not in saved[0]["content"]:
            raise CheckFailure("Terminal answer was not persisted exactly once")
        used_citations = {int(number) for number in re.findall(r"\[(\d+)\]", saved[0]["content"])}
        available_citations = {citation["number"] for citation in terminal.get("citations") or []}
        if (
            config.get("require_citations")
            and seed
            and (not used_citations or not used_citations.issubset(available_citations))
        ):
            raise CheckFailure("Answer does not actually cite its verified available sources")
        response = client.get(f"/api/chat/turns/{turn}")
        response.raise_for_status()
        if response.json()["state"] not in {"committed", "acknowledged"}:
            raise CheckFailure("Chat turn did not commit")
        result = {
            "kind": "real_http_chat",
            "model": model,
            "mode": mode,
            "seed": seed,
            "long_stream_sample": long_sample,
            "active_admin_observation": admin_observation,
            "attempt_timings": attempt_timings,
            "usage": execution.get("usage"),
            "tool_artifacts": artifacts,
            "conversation_id": conversation,
            "turn_id": turn,
            "job_id": terminal["job_id"],
            "message_id": terminal["message_id"],
            "elapsed_seconds": time.monotonic() - began,
            "first_token_seconds": first_token,
            "token_frames": token_count,
            "progress_stages": sorted(progress),
            "citations": len(terminal.get("citations") or []),
            "used_citation_numbers": sorted(used_citations),
            "answer_sha256": hashlib.sha256(saved[0]["content"].encode()).hexdigest(),
            "answer_words": len(saved[0]["content"].split()),
        }
        save(config["evidence"], result, append=True)
        state["cycle"] += 1
        if long_sample:
            state["long_sample_done"] = True
        state.pop("pending", None)
        save(state_path, state)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--read-only", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    config = {}
    try:
        config = json.loads(args.config.read_text())
        result = probe(config, args.read_only)
    except Exception as exc:
        failure = {
            "ok": False,
            "kind": "real_http_chat",
            "reason": str(exc) if isinstance(exc, CheckFailure) else type(exc).__name__,
        }
        if isinstance(exc, httpx.HTTPStatusError):
            failure["http_status"] = exc.response.status_code
        if config.get("evidence"):
            save(config["evidence"], failure, append=True)
        print(json.dumps(failure))
        raise SystemExit(1) from None
    print(json.dumps({"ok": True, **result}, sort_keys=True))


if __name__ == "__main__":
    main()
