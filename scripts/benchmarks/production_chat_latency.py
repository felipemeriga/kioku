"""Private latency probes through the exact authenticated web chat HTTP/SSE path.

No native runner, prompt overrides, retrieval mocks, or credential refresh. Output
contains private conversations and must stay outside git. First text means SSE
delivery, not DOM paint. A completed probe verifies the published message too.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from benchmark_guard import budget_error, coordinator_lock


def private_json(path, value):
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as target:
        json.dump(value, target, indent=2, ensure_ascii=False)
        target.write("\n")


def append_event(path, value):
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "a") as target:
        target.write(json.dumps(value, ensure_ascii=False) + "\n")


def validate_manifest(manifest):
    chains = manifest.get("conversations")
    if not isinstance(chains, list) or not 1 <= len(chains) <= 128:
        raise ValueError("Manifest needs 1..128 benchmark conversation chains")
    identifiers = set()
    for chain in chains:
        if not isinstance(chain, dict) or set(chain) - {"id", "turns"}:
            raise ValueError(
                "Each chain supports only id and turns; existing chats are forbidden"
            )
        turns = chain.get("turns")
        if not isinstance(turns, list) or not 1 <= len(turns) <= 32:
            raise ValueError("Each conversation needs 1..32 turns")
        for case in turns:
            if not isinstance(case, dict):
                raise TypeError("Each turn must be an object")
            if set(case) - {
                "id",
                "content",
                "model",
                "mode",
                "reasoning_effort",
                "scope_folder_id",
                "scope_filename",
                "timezone",
                "provenance",
            }:
                raise ValueError("Unsupported case field")
            identifier = case.get("id")
            if (
                not isinstance(identifier, str)
                or not identifier
                or len(identifier) > 120
            ):
                raise ValueError("Case id must be a nonempty string <=120 characters")
            if identifier in identifiers:
                raise ValueError("Duplicate case id")
            identifiers.add(identifier)
            content = case.get("content")
            if (
                not isinstance(content, str)
                or not content.strip()
                or len(content) > 100_000
            ):
                raise ValueError("Case content must contain 1..100000 characters")
            if case.get("model", "haiku") not in {"haiku", "sonnet", "opus"}:
                raise ValueError("Unsupported model")
            if case.get("mode", "agentic") != "agentic":
                raise ValueError("This latency cohort measures agentic chat only")
            if case.get("reasoning_effort", "low") not in {"low", "medium", "high"}:
                raise ValueError("Unsupported reasoning effort")
            if case.get("scope_folder_id"):
                uuid.UUID(case["scope_folder_id"])
            ZoneInfo(case.get("timezone", "America/Sao_Paulo"))
    return chains


async def sse_frames(response):
    """Parse SSE records, including multiline data and an unterminated last frame."""
    lines = []
    async for line in response.aiter_lines():
        if not line:
            if lines:
                yield json.loads("\n".join(lines))
                lines = []
        elif line.startswith("data:"):
            lines.append(line[5:].removeprefix(" "))
    if lines:
        yield json.loads("\n".join(lines))


async def measure_turn(client, conversation_id, case, *, resumed, admit, trace=None):
    result = {
        "id": case["id"],
        "conversation_id": conversation_id,
        "turn_id": str(uuid.uuid4()),
        "context": "resumed" if resumed else "fresh",
        "case": case,
        "frames": [],
        "answer": "",
        "success": False,
        "started_at": datetime.now().astimezone().isoformat(),
    }
    emit = trace or (lambda _event: None)
    emit(
        {
            "event": "probe.created",
            "turn_id": result["turn_id"],
            "conversation_id": conversation_id,
            "case_id": case["id"],
        }
    )
    # Admission immediately precedes the inference-triggering POST, including resumed turns.
    rejection = admit()
    if rejection:
        result["error"] = rejection
        return result
    payload = {
        "rebuild_from_committed_history": False,
        "conversation_id": conversation_id,
        "turn_id": result["turn_id"],
        "content": case["content"],
        "model": case.get("model", "haiku"),
        "mode": case.get("mode", "agentic"),
        "reasoning_effort": case.get("reasoning_effort", "low"),
        "debug": False,
        "scope_folder_id": case.get("scope_folder_id"),
        "scope_filename": case.get("scope_filename"),
        "timezone": case.get("timezone", "America/Sao_Paulo"),
    }
    started = time.perf_counter()
    try:
        # Never retry an uncertain POST: it may already own a durable native job.
        async with client.stream("POST", "/api/chat", json=payload) as response:
            result["headers_seconds"] = time.perf_counter() - started
            result["http_status"] = response.status_code
            emit(
                {
                    "event": "http.headers",
                    "seconds": result["headers_seconds"],
                    "status": response.status_code,
                }
            )
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", ""):
                raise ValueError("Expected SSE response")
            async for frame in sse_frames(response):
                elapsed = time.perf_counter() - started
                result["frames"].append({"seconds": elapsed, "data": frame})
                emit({"event": "sse.frame", "seconds": elapsed, "data": frame})
                if frame.get("job_id"):
                    result["job_id"] = frame["job_id"]
                if isinstance(frame.get("token"), str):
                    result["answer"] += frame["token"]
                if isinstance(frame.get("replace"), str):
                    result["answer"] = frame["replace"]
                if (
                    result["answer"].strip()
                    and "first_visible_text_seconds" not in result
                ):
                    result["first_visible_text_seconds"] = elapsed
                if frame.get("error"):
                    result["error"] = str(frame["error"])
                if frame.get("done"):
                    result["complete_seconds"] = elapsed
                    result["message_id"] = frame.get("message_id")
                    result["debug"] = frame.get("debug")
                    result["citations"] = frame.get("citations")
                    break
        if "complete_seconds" not in result:
            raise ValueError("Stream ended without done; request not retried")
        turn_response = await client.get(f"/api/chat/turns/{result['turn_id']}")
        turn_response.raise_for_status()
        result["published_turn"] = turn_response.json()
        saved_response = await client.get(f"/api/conversations/{conversation_id}")
        saved_response.raise_for_status()
        message = next(
            (
                row
                for row in saved_response.json().get("messages", [])
                if row["id"] == result.get("message_id")
            ),
            None,
        )
        result["publication_verified"] = bool(
            message
            and message["role"] == "assistant"
            and message["content"] == result["answer"]
            and result["published_turn"].get("assistant_message_id") == message["id"]
        )
        result["verification_seconds"] = time.perf_counter() - started
        result["success"] = result["publication_verified"] and not result.get("error")
        if not result["success"] and not result.get("error"):
            result["error"] = "Published message did not match completed SSE answer"
    except httpx.HTTPStatusError as exc:
        result["error"] = f"HTTP {exc.response.status_code}; no automatic retry"
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        result["error"] = (
            f"{type(exc).__name__}; inspect private trace; no automatic retry"
        )
    finally:
        result["observed_seconds"] = time.perf_counter() - started
        emit(
            {
                "event": "probe.finished",
                "success": result["success"],
                "seconds": result["observed_seconds"],
                "error": result.get("error"),
            }
        )
    return result


async def run(args, *, transport=None):
    manifest_bytes = Path(args.manifest).read_bytes()
    manifest = json.loads(manifest_bytes)
    chains = validate_manifest(manifest)
    if not 1 <= args.workers <= 4:
        raise ValueError("Workers must be 1..4")
    auth = json.loads(Path(args.auth).read_text())
    if not isinstance(auth.get("access_token"), str) or not auth["access_token"]:
        raise ValueError("Private auth file needs access_token")
    api_base = auth.get("api_base", "https://kioku.api.merigafy.com").rstrip("/")
    if not api_base.startswith("https://"):
        raise ValueError("Authenticated benchmark requires HTTPS")
    if "/" in api_base.removeprefix("https://"):
        raise ValueError("api_base must be an HTTPS origin without path")
    output = Path(args.output)
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    guard = {"config": {"usage_lease": str(Path(args.usage_lease).resolve())}}
    reject = budget_error(guard)
    if reject:
        raise ValueError(reject)
    proof = json.loads(Path(args.deployment_proof).read_text())
    private_json(output / "manifest.json", manifest)
    private_json(
        output / "run.json",
        {
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "api_base": api_base,
            "workers": args.workers,
            "deployment_proof": proof,
            "path": "production HTTP/SSE chat with durable publication",
            "first_text_clock": "client monotonic; SSE delivery, not DOM paint",
            "queue_clock": "server attempt timing retained in debug; no inferred prefetch duration",
        },
    )
    async with httpx.AsyncClient(
        base_url=api_base,
        headers={"Authorization": f"Bearer {auth['access_token']}"},
        timeout=httpx.Timeout(600, connect=20),
        transport=transport,
        follow_redirects=False,
    ) as client:
        preflight = await client.get("/api/chat/models")
        if preflight.status_code != 200:
            raise ValueError(f"Auth/catalog preflight HTTP {preflight.status_code}")
        private_json(output / "model-catalog.json", preflight.json())
        semaphore = asyncio.Semaphore(args.workers)
        results = []

        async def chain_run(index, chain):
            async with semaphore:
                rejection = budget_error(guard)
                if rejection:
                    row = {"chain": index, "error": rejection, "success": False}
                    private_json(output / f"chain-{index:03d}.json", row)
                    results.append(row)
                    return
                created = await client.post("/api/conversations")
                created.raise_for_status()
                conversation_id = created.json()["id"]
                title = f"[Latency benchmark] {chain.get('id', index)}"[:200]
                renamed = await client.patch(
                    f"/api/conversations/{conversation_id}", json={"title": title}
                )
                renamed.raise_for_status()
                for position, case in enumerate(chain["turns"]):
                    trace_path = output / f"trace-{index:03d}-{position:03d}.jsonl"
                    row = await measure_turn(
                        client,
                        conversation_id,
                        case,
                        resumed=position > 0,
                        admit=lambda: budget_error(guard),
                        trace=lambda event, path=trace_path: append_event(path, event),
                    )
                    row["chain"] = index
                    row["position"] = position
                    private_json(output / f"case-{index:03d}-{position:03d}.json", row)
                    results.append(row)
                    # Failed/uncertain prior turns cannot become a valid resumed context.
                    if not row["success"]:
                        break

        outcomes = await asyncio.gather(
            *(chain_run(index, chain) for index, chain in enumerate(chains)),
            return_exceptions=True,
        )
        for index, outcome in enumerate(outcomes):
            if isinstance(outcome, Exception):
                row = {
                    "chain": index,
                    "error": type(outcome).__name__,
                    "success": False,
                }
                private_json(output / f"chain-{index:03d}-error.json", row)
                results.append(row)
        summary = {
            "results": len(results),
            "successful": sum(bool(r["success"]) for r in results),
            "planned_turns": sum(len(chain["turns"]) for chain in chains),
            "rows": [
                {
                    k: r.get(k)
                    for k in (
                        "id",
                        "chain",
                        "position",
                        "context",
                        "success",
                        "error",
                        "job_id",
                        "first_visible_text_seconds",
                        "complete_seconds",
                        "headers_seconds",
                    )
                }
                for r in results
            ],
        }
        private_json(output / "summary.json", summary)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("auth", "manifest", "usage-lease", "deployment-proof", "output"):
        parser.add_argument(f"--{field}", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    with coordinator_lock():
        summary = asyncio.run(run(args))
    print(
        json.dumps(
            {"planned": summary["planned_turns"], "successful": summary["successful"]}
        )
    )


if __name__ == "__main__":
    main()
