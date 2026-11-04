"""Bounded real three-conversation load + reserved metadata-child acceptance.

Requires the operator's integrated readiness. Runs exactly three short real
Haiku agentic jobs, one explicitly invoking metadata, while measuring existing
HTTP read responsiveness and actual queue/admin telemetry. Uses the private
HTTP probe config; preserves synthetic fixture IDs and native accounting.
The config also supplies journal_folder_id, journal_year and journal_month for
the owner's known nonempty journal metadata routes. No journal text is logged.
"""

import argparse
import concurrent.futures
import hashlib
import json
import logging
import stat
import threading
import time
from pathlib import Path

import httpx

from tsukai_chat_lifecycle_acceptance import body, conversation, frames
from tsukai_http_acceptance import CheckFailure, save


def load_read_paths(config):
    return [
        ("health", "/api/health", {}),
        ("folders", "/api/folders", {}),
        ("documents", "/api/documents", {"folder_id": config["folder_id"]}),
        ("conversations", "/api/conversations", {}),
        (
            "existing_learnings",
            f"/api/folders/{config['journal_folder_id']}/learnings",
            {},
        ),
        (
            "existing_calendar",
            f"/api/folders/{config['journal_folder_id']}/learning-days",
            {
                "year": config["journal_year"],
                "month": config["journal_month"],
                "timezone": "America/Sao_Paulo",
            },
        ),
    ]


def run(config, scenario="metadata-first"):
    token = Path(config["token_file"])
    if (
        not config["fixture_name"].startswith("tsukai-e2e-")
        or stat.S_IMODE(token.stat().st_mode) != 0o600
    ):
        raise CheckFailure("Isolated fixture and private token required")
    headers = {"Authorization": "Bearer " + token.read_text().strip()}
    options = {
        "base_url": config["url"],
        "headers": headers,
        "timeout": httpx.Timeout(180, connect=20),
    }
    identifiers = []
    with httpx.Client(**options) as client:
        preflight = []
        for name, path, params in load_read_paths(config):
            response = client.get(path, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if name == "existing_calendar" and not data.get("days"):
                raise CheckFailure("Known nonempty calendar preflight failed before load admission")
            preflight.append({"name": name, "status": response.status_code})
        response = client.get("/api/usage/native/active-sessions", timeout=10)
        response.raise_for_status()
        telemetry = response.json()
        if (
            not telemetry.get("available")
            or telemetry.get("sessions")
            or (telemetry.get("queued_counts") or {}).get("total", 0)
        ):
            raise CheckFailure("Load deferred before admission: runtime is unavailable or busy")
        save(
            config["evidence"],
            {"kind": "real_load_preflight", "ok": True, "checks": preflight},
            append=True,
        )
        for index in range(3):
            identifiers.append(conversation(client, config, "load-" + str(index)))

    metadata_admitted = threading.Event()

    def job(index):
        content = (
            (
                "Use the query_documents_metadata tool to count distinct uploaded document files in this exact fixture scope. "
                "Report the count briefly, then say load-metadata-complete."
            )
            if index == 0 and scenario == "metadata-first"
            else (
                "Use knowledge_base_search exactly once in this fixture scope "
                "for the acceptance guide. "
                "Cite its source and explain in one short sentence "
                "what this synthetic repository does."
            )
        )
        request = body(config, identifiers[index], content)
        began = time.monotonic()
        try:
            with httpx.Client(**options) as client:
                final, deltas = None, 0
                with client.stream("POST", "/api/chat", json=request) as response:
                    for frame in frames(response):
                        if (
                            index == 0
                            and (frame.get("progress") or {}).get("type")
                            == "attempt.started"
                        ):
                            metadata_admitted.set()
                        deltas += bool(frame.get("token"))
                        if frame.get("done"):
                            final = frame
                if not final or not final.get("message_id"):
                    raise CheckFailure(
                        "Concurrent root has no durable terminal message"
                    )
        except Exception as exc:
            save(
                config["evidence"],
                {
                    "kind": "real_load_job",
                    "ok": False,
                    "index": index,
                    "conversation_id": identifiers[index],
                    "turn_id": request["turn_id"],
                    "reason": str(exc)
                    if isinstance(exc, CheckFailure)
                    else type(exc).__name__,
                },
                append=True,
            )
            raise
        execution = (final.get("debug") or {}).get("execution") or {}
        tools = (final.get("debug") or {}).get("tool_calls") or []
        if not deltas:
            raise CheckFailure("Concurrent actual chat returned no deltas")
        if (
            index == 0
            and scenario == "metadata-first"
            and not any(
                "query_documents_metadata" in tool.get("name", "") for tool in tools
            )
        ):
            raise CheckFailure(
                "Real load job did not invoke the reserved metadata-child path"
            )
        metadata_count = None
        if index == 0 and scenario == "metadata-first":
            metadata_tool = next(
                tool
                for tool in tools
                if "query_documents_metadata" in tool.get("name", "")
            )
            if metadata_tool.get("is_error") or not metadata_tool.get("artifact_id"):
                raise CheckFailure(
                    "Metadata-child tool failed or lacks its actual result artifact"
                )
            with httpx.Client(**options) as client:
                artifact = client.get(
                    f"/api/chat/jobs/{final['job_id']}/artifacts/{metadata_tool['artifact_id']}"
                )
                artifact.raise_for_status()
                payload = artifact.json()
            answer = json.loads(payload["result"])
            metadata_count = (answer.get("data") or {}).get("count")
            if answer.get("operation") != "count_files" or not isinstance(
                metadata_count, int
            ):
                raise CheckFailure(
                    "Actual metadata-child artifact has no typed distinct-file count"
                )
            if (
                "expected_document_count" in config
                and metadata_count != config["expected_document_count"]
            ):
                raise CheckFailure(
                    "Actual metadata-child count differs from current fixture documents"
                )
            if (payload["trace"].get("effective_scope") or {}).get("folder_ids") != [
                config["folder_id"]
            ]:
                raise CheckFailure(
                    "Actual metadata-child result scope differs from the fixture"
                )
        result = {
            "index": index,
            "conversation_id": identifiers[index],
            "turn_id": request["turn_id"],
            "job_id": final["job_id"],
            "elapsed_seconds": time.monotonic() - began,
            "delta_frames": deltas,
            "attempt_timings": execution.get("timings"),
            "usage": execution.get("usage"),
            "tool_names": [tool.get("name") for tool in tools],
            "metadata_count": metadata_count,
        }
        save(
            config["evidence"],
            {"kind": "real_load_job", "ok": True, **result},
            append=True,
        )
        return result

    reads = []
    samples = []
    stop_monitor = threading.Event()
    fast_overlap_seen = threading.Event()
    monitor_errors = []

    def monitor_admin():
        with httpx.Client(**options) as client:
            while not stop_monitor.is_set():
                tick = time.monotonic()
                try:
                    response = client.get(
                        "/api/usage/native/active-sessions", timeout=10
                    )
                    response.raise_for_status()
                    telemetry = response.json()
                    sessions = telemetry.get("sessions") or []
                    samples.append(
                        {
                            "elapsed_seconds": time.monotonic() - began,
                            "queued_counts": telemetry.get("queued_counts"),
                            "sessions": [
                                {
                                    key: session.get(key)
                                    for key in (
                                        "job_id",
                                        "attempt_id",
                                        "profile",
                                        "caller",
                                        "state",
                                        "pid",
                                        "conversation_id",
                                        "folder_ids",
                                        "native_session_id",
                                    )
                                }
                                for session in sessions
                            ],
                        }
                    )
                    save(
                        config["evidence"],
                        {"kind": "real_load_admin_sample", **samples[-1]},
                        append=True,
                    )
                    current = samples[-1]["sessions"]
                    if (
                        any(
                            a.get("profile") == "metadata_child" and a.get("pid")
                            for a in current
                        )
                        and sum(
                            bool(a.get("pid"))
                            and a.get("conversation_id") in identifiers
                            for a in current
                        )
                        >= 2
                    ):
                        fast_overlap_seen.set()
                except Exception as exc:
                    monitor_errors.append(type(exc).__name__)
                    save(
                        config["evidence"],
                        {"kind": "real_load_admin_error", "reason": type(exc).__name__},
                        append=True,
                    )
                interval = 5 if fast_overlap_seen.is_set() else 1
                stop_monitor.wait(max(0.05, interval - (time.monotonic() - tick)))

    began = time.monotonic()
    with (
        concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor,
        httpx.Client(**options) as client,
    ):
        monitor_future = executor.submit(monitor_admin)
        try:
            if scenario == "metadata-first":
                futures = [executor.submit(job, 0)]
                deadline = time.monotonic() + 90
                while not metadata_admitted.wait(0.25):
                    if futures[0].done():
                        futures[0].result()
                        raise CheckFailure(
                            "Metadata root finished before actual admission was observed"
                        )
                    if time.monotonic() > deadline:
                        raise CheckFailure(
                            "Metadata root was not admitted; other load jobs were not started"
                        )
                futures.extend(executor.submit(job, index) for index in (1, 2))
            else:
                futures = [executor.submit(job, index) for index in range(3)]
            while not all(future.done() for future in futures):
                for name, path, params in load_read_paths(config):
                    start = time.monotonic()
                    response = client.get(path, params=params, timeout=10)
                    response.raise_for_status()
                    elapsed = time.monotonic() - start
                    data = response.json()
                    item_count = (
                        len(data)
                        if isinstance(data, list)
                        else len(data.get("days", data.get("learnings", [])))
                    )
                    if name == "existing_calendar" and not item_count:
                        raise CheckFailure(
                            "Known nonempty calendar lost metadata during concurrent load"
                        )
                    reads.append(
                        {
                            "name": name,
                            "seconds": elapsed,
                            "status": response.status_code,
                            "item_count": item_count,
                            "sha256": hashlib.sha256(
                                json.dumps(data, sort_keys=True).encode()
                            ).hexdigest(),
                        }
                    )
                    save(
                        config["evidence"],
                        {"kind": "real_load_read_sample", **reads[-1]},
                        append=True,
                    )
                time.sleep(2)
            jobs, failures = [], []
            for index, future in enumerate(futures):
                try:
                    jobs.append(future.result())
                except Exception as exc:
                    failures.append(
                        {
                            "index": index,
                            "reason": str(exc)
                            if isinstance(exc, CheckFailure)
                            else type(exc).__name__,
                        }
                    )
        finally:
            stop_monitor.set()
            monitor_future.result(timeout=20)

    result = {
        "kind": "real_three_conversation_load",
        "scenario": scenario,
        "elapsed_seconds": time.monotonic() - began,
        "jobs": jobs,
        "failures": failures,
        "read_samples": reads,
        "admin_samples": samples,
        "admin_monitor_errors": monitor_errors,
        "fast_pid_overlap_seen": fast_overlap_seen.is_set(),
        "maximum_read_seconds": max(sample["seconds"] for sample in reads),
    }
    save(config["evidence"], result, append=True)
    if failures:
        raise CheckFailure(
            "Concurrent root failures recorded with all read/admin/job evidence preserved"
        )
    if result["maximum_read_seconds"] > config.get("max_read_seconds", 3):
        raise CheckFailure("Existing HTTP reads exceeded the bounded load responsiveness threshold")
    root_counts = [
        sum(session.get("conversation_id") in identifiers for session in sample["sessions"])
        for sample in samples
    ]
    if max(root_counts) > 2:
        raise CheckFailure(
            "Actual root concurrency exceeded configured two-root capacity"
        )
    if scenario == "metadata-first" and not any(
        sum(
            session.get("profile") == "metadata_child"
            and session.get("folder_ids") == [config["folder_id"]]
            and session.get("pid") is not None
            for session in sample["sessions"]
        )
        >= 1
        and sum(
            session.get("conversation_id") in identifiers and session.get("pid") is not None
            for session in sample["sessions"]
        )
        >= 2
        for sample in samples
    ):
        raise CheckFailure(
            "Did not observe reserved metadata child concurrent with two active roots"
        )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--scenario",
        choices=("metadata-first", "simultaneous"),
        default="metadata-first",
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    config = json.loads(args.config.read_text())
    try:
        result = run(config, args.scenario)
    except Exception as exc:
        record = {
            "kind": "real_three_conversation_load",
            "ok": False,
            "reason": str(exc) if isinstance(exc, CheckFailure) else type(exc).__name__,
        }
        if isinstance(exc, httpx.HTTPStatusError):
            record["http_status"] = exc.response.status_code
        save(config["evidence"], record, append=True)
        print(json.dumps(record))
        raise SystemExit(1) from None
    print(
        json.dumps(
            {
                "ok": True,
                "kind": result["kind"],
                "job_count": len(result["jobs"]),
                "read_sample_count": len(result["read_samples"]),
                "maximum_read_seconds": result["maximum_read_seconds"],
                "elapsed_seconds": result["elapsed_seconds"],
            }
        )
    )


if __name__ == "__main__":
    main()
