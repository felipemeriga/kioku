"""Run candidate retrieval plus the pinned native generator against private cases.

Input JSON (stdin/file): config for shadow_tools, system_prompt, and cases with
id, question, folder_ids, optional model/effort and oracle_evidence. Expected
answers are never sent to the model. Results include every failure and the
exact retrieved evidence; grading is separate. No production domain writes.

Each batch requires subscription_usage: five_hour/seven_day percentages,
observed_at epoch seconds, and account_verified=true from the operator's live
meter check. Run at most two sequential cases. Stop admissions at75percent to
leave headroom below the user's80percent ceiling; missing/stale data fails closed.
"""

import argparse
import asyncio
import hashlib
import inspect
import json
import math
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from tsukai.config import Settings
from tsukai.native import NativeRunner
from tsukai.validation import NativeError

from tsukai.protocol import JobRequest

TOOLS = [
    "knowledge_base_search",
    "code_graph_lookup",
    "search_agent_history",
    "read_agent_evidence",
    "recent_changes",
]


def budget_error(payload):
    """Require fresh operator-observed quota; leave headroom below the user's80% cap."""
    snapshot = payload.get("subscription_usage") or {}
    values = [snapshot.get(k) for k in ("five_hour", "seven_day", "observed_at")]
    if any(type(v) not in (float, int) or not math.isfinite(v) for v in values):
        return "usage_snapshot_required"
    five_hour, seven_day, observed_at = values
    if not 0 <= five_hour <= 100 or not 0 <= seven_day <= 100:
        return "usage_snapshot_invalid"
    if snapshot.get("account_verified") is not True:
        return "usage_account_unverified"
    if not -5 <= time.time() - observed_at <= 90:
        return "usage_snapshot_stale"
    if max(five_hour, seven_day) >= 75:
        return "usage_reserve_reached"
    return None


async def run(payload, workers):
    if workers != 1 or not 1 <= len(payload["cases"]) <= 2:
        raise ValueError(
            "Usage-guarded benchmarks allow at most two sequential cases per batch"
        )
    config = payload["config"]
    runner_file = Path(inspect.getfile(NativeRunner)).resolve()
    if config.get("remote") and not runner_file.is_relative_to(
        Path(config["remote"]) / "tsukai/src"
    ):
        raise ValueError(
            "Native runner did not load from the expected candidate source"
        )
    runner_hash = hashlib.sha256(runner_file.read_bytes()).hexdigest()
    base = f"http://kioku-backend:{config['port']}"
    headers = {"Authorization": "Bearer " + config["token"]}
    semaphore = asyncio.Semaphore(workers)
    quota_exhausted = asyncio.Event()
    native = NativeRunner(Settings())
    await native.verify_version()

    async def one(case):
        async with semaphore:
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", case["id"]):
                raise ValueError("Invalid case ID")
            began = time.monotonic()
            result = {
                "id": case["id"],
                "domain": case["domain"],
                "model": case.get("model", "claude-haiku-5-5"),
                "effort": case.get("effort", "low"),
                "stage": "retrieval",
                "success": False,
                "question": case["question"],
                "runner_source_sha256": runner_hash,
            }
            if quota_exhausted.is_set():
                result.update(error_code="not_run_after_quota_limit", total_seconds=0.0)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                return
            error = budget_error(payload)
            if error:
                result.update(error_code=error, total_seconds=0.0)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                return
            result["subscription_usage_before"] = payload["subscription_usage"]
            async with httpx.AsyncClient(timeout=180) as client:
                try:
                    oracle = case.get("oracle_evidence")
                    if oracle is None:
                        response = await client.post(
                            base + "/prepare",
                            headers=headers,
                            json={
                                "case": case["id"],
                                "question": case["question"],
                                "folder_ids": case["folder_ids"],
                                "timezone": case.get("timezone", "America/Sao_Paulo"),
                                "skip_prefetch": case.get("skip_prefetch", False),
                            },
                        )
                        response.raise_for_status()
                        evidence = response.json()["evidence"]
                        answer_instruction = response.json().get("answer_instruction")
                        if not isinstance(answer_instruction, str) or not answer_instruction:
                            raise NativeError("missing_answer_contract")
                    else:
                        result["stage"] = "oracle"
                        evidence = oracle
                        answer_instruction = "Answer from the supplied evidence; cite supporting sources."
                    result["prefetch_seconds"] = time.monotonic() - began
                    conversation, session = str(uuid4()), str(uuid4())
                    zone = case.get("timezone", "America/Sao_Paulo")
                    time_context = (
                        f"Current local timestamp: {datetime.now(ZoneInfo(zone)).isoformat()}; "
                        f"user timezone: {zone}. Resolve relative dates in this timezone. "
                        "Weeks start Monday. Record time is not necessarily described-event time."
                    )
                    req = JobRequest(
                        idempotency_key=case["id"],
                        owner_id=config["owner_id"],
                        caller="backend",
                        operation="rag_agent",
                        profile="chat",
                        conversation_id=conversation,
                        model=result["model"],
                        reasoning_effort=result["effort"],
                        max_tokens=6000,
                        max_turns=8,
                        system_prompt=payload["system_prompt"],
                        prompt=json.dumps(
                            {
                                "canonical_history": [],
                                "user_message": case["question"],
                                "time_context": time_context,
                                "current_turn_evidence": evidence,
                                "citation_instruction": answer_instruction,
                            }
                        ),
                        tool_allowlist=TOOLS if oracle is None else [],
                        tool_capability_ref=case["id"] if oracle is None else None,
                        metadata={"history_transport": "resume-delta-v1"},
                    )
                    mcp = (
                        {
                            "mcpServers": {
                                "kioku": {
                                    "type": "http",
                                    "url": base + "/mcp/",
                                    "headers": {
                                        **headers,
                                        "X-Kioku-Benchmark-Case": case["id"],
                                    },
                                }
                            }
                        }
                        if oracle is None
                        else None
                    )
                    attempt = {
                        "id": str(uuid4()),
                        "native_session_id": session,
                        "resume": False,
                        "counter_segment": 0,
                    }
                    events = []

                    async def emit(kind, data):
                        events.append({"kind": kind, "data": data})

                    generation = time.monotonic()
                    with tempfile.TemporaryDirectory(
                        prefix="kioku-quality-"
                    ) as workspace:
                        if error := budget_error(payload):
                            raise NativeError(error)
                        response = await native.run(
                            {"attempt": attempt, "workspace": workspace},
                            req,
                            emit,
                            mcp=mcp,
                        )
                    result.update(
                        success=True,
                        answer=response["text"],
                        usage=response.get("usage"),
                        events=events,
                        generation_seconds=time.monotonic() - generation,
                    )
                    if oracle is None:
                        saved = await client.get(
                            base + "/result/" + case["id"], headers=headers
                        )
                        saved.raise_for_status()
                        result["retrieval"] = saved.json()
                    else:
                        result["retrieval"] = {"evidence": oracle}
                except (NativeError, httpx.HTTPError, ValueError) as exc:
                    result["error_code"] = getattr(exc, "code", type(exc).__name__)
                    if result["error_code"] == "quota_limited":
                        quota_exhausted.set()
                    if isinstance(exc, httpx.HTTPStatusError):
                        result["http_status"] = exc.response.status_code
                result["total_seconds"] = time.monotonic() - began
                print(json.dumps(result, ensure_ascii=False), flush=True)

    await asyncio.gather(*(one(case) for case in payload["cases"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("/dev/stdin"))
    parser.add_argument("--workers", type=int, choices=[1], default=1)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text())
    if not 1 <= len(payload["cases"]) <= 2:
        raise ValueError(
            "Provide one or two cases with a fresh verified subscription usage snapshot"
        )
    asyncio.run(run(payload, args.workers))
