"""Bounded real three-conversation load + reserved metadata-child acceptance.

Requires the operator's integrated readiness. Runs exactly three short real
Haiku agentic jobs, one explicitly invoking metadata, while measuring existing
HTTP read responsiveness and actual queue/admin telemetry. Uses the private
HTTP probe config; preserves synthetic fixture IDs and native accounting.
"""

import argparse
import concurrent.futures
import json
import logging
import stat
import time
from pathlib import Path

import httpx

from tsukai_chat_lifecycle_acceptance import body, conversation, terminal
from tsukai_http_acceptance import CheckFailure, save


def run(config):
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
        for index in range(3):
            identifiers.append(conversation(client, config, "load-" + str(index)))

    def job(index):
        content = (
            (
                "Use the query_documents_metadata tool to count documents in this exact fixture scope. "
                "Report the count briefly, then say load-metadata-complete."
            )
            if index == 0
            else (
                "Use knowledge_base_search exactly once in this fixture scope for the acceptance guide. "
                "Cite its source and explain in one short sentence what this synthetic repository does."
            )
        )
        request = body(config, identifiers[index], content)
        began = time.monotonic()
        with httpx.Client(**options) as client:
            final, deltas = terminal(client, request)
        execution = (final.get("debug") or {}).get("execution") or {}
        tools = (final.get("debug") or {}).get("tool_calls") or []
        if not deltas:
            raise CheckFailure("Concurrent actual chat returned no deltas")
        if index == 0 and not any(
            "query_documents_metadata" in tool.get("name", "") for tool in tools
        ):
            raise CheckFailure(
                "Real load job did not invoke the reserved metadata-child path"
            )
        return {
            "index": index,
            "conversation_id": identifiers[index],
            "turn_id": request["turn_id"],
            "job_id": final["job_id"],
            "elapsed_seconds": time.monotonic() - began,
            "delta_frames": deltas,
            "attempt_timings": execution.get("timings"),
            "usage": execution.get("usage"),
            "tool_names": [tool.get("name") for tool in tools],
        }

    reads = []
    samples = []
    began = time.monotonic()
    with (
        concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor,
        httpx.Client(**options) as client,
    ):
        futures = [executor.submit(job, index) for index in range(3)]
        while not all(future.done() for future in futures):
            for name, path, params in [
                ("health", "/health", {}),
                ("folders", "/api/folders", {}),
                ("documents", "/api/documents", {"folder_id": config["folder_id"]}),
            ]:
                start = time.monotonic()
                response = client.get(path, params=params, timeout=10)
                response.raise_for_status()
                elapsed = time.monotonic() - start
                reads.append(
                    {"name": name, "seconds": elapsed, "status": response.status_code}
                )
            response = client.get("/api/usage/native/active-sessions", timeout=10)
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
                            )
                        }
                        for session in sessions
                    ],
                }
            )
            time.sleep(2)
        jobs = [future.result() for future in futures]
    result = {
        "kind": "real_three_conversation_load",
        "elapsed_seconds": time.monotonic() - began,
        "jobs": jobs,
        "read_samples": reads,
        "admin_samples": samples,
        "maximum_read_seconds": max(sample["seconds"] for sample in reads),
    }
    save(config["evidence"], result, append=True)
    if result["maximum_read_seconds"] > config.get("max_read_seconds", 3):
        raise CheckFailure(
            "Existing HTTP reads exceeded the bounded load responsiveness threshold"
        )
    if not any(
        sum(
            session.get("profile") == "metadata_child" for session in sample["sessions"]
        )
        >= 1
        and sum(
            session.get("profile") != "metadata_child" for session in sample["sessions"]
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
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    config = json.loads(args.config.read_text())
    try:
        result = run(config)
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
