"""Durable machine-result receipts, usage copy and acknowledgement retries."""

import asyncio
import logging
import os
from dataclasses import asdict, replace
from datetime import datetime, timezone

from db.client import get_supabase_thread_safe
from services.ai.accounting import record_job_usage
from services.ai.scope import ExecutionScope

logger = logging.getLogger(__name__)


def finish_receipt(receipt: dict):
    from services.ai.facade import client_for

    scope = ExecutionScope(
        **{
            **receipt["scope"],
            "folder_ids": tuple(receipt["scope"]["folder_ids"]),
            "tool_allowlist": tuple(receipt["scope"].get("tool_allowlist", [])),
        }
    )
    sb = get_supabase_thread_safe()
    sb.table("tsukai_completion_receipts").update(
        {
            "last_attempt_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("job_id", receipt["job_id"]).execute()
    client = client_for(scope, receipt["operation"], receipt["profile"])
    try:
        # Only a terminal job has immutable final attempt counters. Copying usage
        # before checking status can freeze a partial snapshot during a transition.
        status = client.status(receipt["job_id"])["status"]
        if status not in {"completed", "failed", "cancelled", "uncertain"}:
            raise RuntimeError("consumption awaits a terminal native job")
        record_job_usage(
            client,
            scope,
            receipt["operation"],
            receipt["payload"].get("model", "unknown"),
            receipt["job_id"],
            source=receipt["consumer"],
        )
        acknowledge = status == "completed" and receipt["payload"].get(
            "acknowledge_completed", True
        )
        if acknowledge:
            client.acknowledge(receipt["job_id"], scope.caller, receipt["reference"])
        sb.table("tsukai_completion_receipts").update(
            {
                "processed": True,
                "acknowledged": acknowledge,
            }
        ).eq("job_id", receipt["job_id"]).execute()
    finally:
        client.close()


def consume_result(
    scope: ExecutionScope,
    operation: str,
    profile: str,
    job_id: str,
    consumer: str,
    reference: str,
    payload: dict,
):
    # Read/ack grants can be renewed after the execution deadline. They omit the
    # mandatory admission digest and cannot submit inference requests.
    read_scope = replace(scope, expires_at=None)
    receipt = {
        "job_id": job_id,
        "owner_id": scope.owner_id,
        "conversation_id": scope.conversation_id,
        "scope": asdict(read_scope),
        "operation": operation,
        "profile": profile,
        "consumer": consumer,
        "reference": reference,
        "payload": payload,
    }
    sb = get_supabase_thread_safe()
    sb.table("tsukai_completion_receipts").upsert(
        receipt, on_conflict="job_id", ignore_duplicates=True
    ).execute()
    # Output is durably consumed now. Failure to copy accounting/ACK must not
    # turn that successful domain effect into an error or start new inference.
    try:
        finish_receipt(receipt)
    except Exception as exc:
        logger.warning(
            "native completion acknowledgement deferred for %s (%s)", job_id, type(exc).__name__
        )


def reconcile_receipts():
    rows = (
        get_supabase_thread_safe()
        .table("tsukai_completion_receipts")
        .select("*")
        .eq("processed", False)
        .order("last_attempt_at")
        .limit(50)
        .execute()
        .data
        or []
    )
    for receipt in rows:
        try:
            finish_receipt(receipt)
        except Exception as exc:
            logger.warning(
                "native receipt retry deferred for %s (%s)", receipt["job_id"], type(exc).__name__
            )


async def consumption_loop():
    while True:
        if os.getenv("TSUKAI_URL"):
            try:
                await asyncio.to_thread(reconcile_receipts)
            except Exception:
                logger.warning("native receipt scan deferred")
        await asyncio.sleep(5)
