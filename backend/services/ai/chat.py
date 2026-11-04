"""Durable product-side outbox, publication and replay adapter for native chat."""

import asyncio
import json
import logging
import os
import threading
from uuid import uuid4

import httpx
from fastapi import HTTPException

from db.client import get_supabase_thread_safe
from services.ai.accounting import record_job_usage
from services.ai.client import ExecutionError
from services.ai.evidence import DurableCitations, save_trace, sources_for
from services.ai.facade import client_for
from services.ai.scope import ExecutionScope
from services.llm import MODEL_FOR_TASK, Task
from services.rag import SYSTEM_PROMPT
from services.scope import descendant_folder_ids
from services.tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)
TOOLS = tuple(tool["name"] for tool in TOOL_DEFINITIONS)


def owned_turn(owner_id: str, *, turn_id: str | None = None, job_id: str | None = None) -> dict:
    query = (
        get_supabase_thread_safe().table("tsukai_chat_turns").select("*").eq("owner_id", owner_id)
    )
    query = query.eq("id", turn_id) if turn_id else query.eq("job_id", job_id)
    rows = query.limit(1).execute().data or []
    if not rows:
        raise HTTPException(404, "Execution not found")
    return rows[0]


def turn_scope(turn: dict) -> ExecutionScope:
    request = turn["request"]
    # Revocation applies to replay/publication as well as tool calls.
    sb = get_supabase_thread_safe()
    folders = request["folder_ids"]
    if folders:
        rows = (
            sb.table("folders")
            .select("id")
            .eq("user_id", turn["owner_id"])
            .in_("id", folders)
            .execute()
            .data
            or []
        )
        if set(folders) != {row["id"] for row in rows}:
            raise HTTPException(403, "Execution scope changed")
    return ExecutionScope(
        turn["owner_id"],
        tuple(folders),
        conversation_id=turn["conversation_id"],
        tool_allowlist=tuple(request["tool_allowlist"]),
    )


def prepare_turn(
    *,
    owner_id: str,
    conversation_id: str,
    content: str,
    turn_id: str | None,
    model: str,
    mode: str,
    rebuild: bool = False,
    folder_id: str | None,
    filename: str | None,
) -> dict:
    sb = get_supabase_thread_safe()
    turn_id = turn_id or str(uuid4())
    existing = (
        sb.table("tsukai_chat_turns")
        .select("*")
        .eq("id", turn_id)
        .eq("owner_id", owner_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    intent = {
        "content": content,
        "model": model,
        "mode": mode,
        "scope_folder_id": folder_id,
        "scope_filename": filename,
        "rebuild": rebuild,
    }
    if existing:
        turn = existing[0]
        if (
            turn["conversation_id"] != conversation_id
            or turn["request"]["metadata"]["intent"] != intent
        ):
            raise HTTPException(409, "Turn idempotency conflict")
        return turn
    if folder_id:
        folders = descendant_folder_ids(sb, folder_id, owner_id)
    else:
        folders = [
            row["id"]
            for row in sb.table("folders").select("id").eq("user_id", owner_id).execute().data or []
        ]
    if len(folders) > 100:
        raise HTTPException(422, "Choose a narrower folder scope for native chat")
    history = (
        sb.table("messages")
        .select("id,role,content")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
        .data
        or []
    )
    native_turns = (
        sb.table("tsukai_chat_turns")
        .select("user_message_id,state")
        .eq("owner_id", owner_id)
        .eq("conversation_id", conversation_id)
        .execute()
        .data
        or []
    )
    incomplete_users = {
        turn["user_message_id"]
        for turn in native_turns
        if turn["state"] not in {"committed", "acknowledged"}
    }
    history = [
        {"role": message["role"], "content": message["content"]}
        for message in history
        if message.get("id") not in incomplete_users
    ]
    prompt = json.dumps(
        {
            "canonical_history": history[-60:],
            "user_message": content,
            "evidence_namespace": turn_id,
        },
        ensure_ascii=False,
    )
    task = Task.RAG_AGENT_SONNET if model == "sonnet" else Task.RAG_AGENT
    request = {
        "schema_version": 1,
        "idempotency_key": turn_id,
        "owner_id": owner_id,
        "caller": "backend",
        "operation": task.value,
        "profile": "completion" if mode == "plain" else "chat",
        "prompt": prompt,
        "system_prompt": SYSTEM_PROMPT
        + (
            "\nOnly use Kioku MCP retrieval tools. Prior conversation citations belong to prior "
            "turns; cite only evidence returned for this current turn. Do not use local files, "
            "shells, web tools outside Kioku, or claim native memory proves repository facts."
        ),
        "model": MODEL_FOR_TASK[task],
        "max_tokens": 6000,
        "max_turns": 8,
        "thinking_tokens": 2048 if mode == "deep" else 0,
        "folder_ids": folders,
        "tool_allowlist": [] if mode == "plain" else list(TOOLS),
        "metadata": {"turn_id": turn_id, "intent": intent},
    }
    if mode != "plain":
        request["conversation_id"] = conversation_id
        request["rebuild_from_committed_history"] = rebuild
        request["tool_capability_ref"] = turn_id
    else:
        # One authoritative retrieval before fresh, tool-disabled generation.
        retrieval = []
        evidence = execute_tool(
            "knowledge_base_search",
            {"query": content},
            owner_id,
            fast_mode=True,
            scope_folder_ids=folders,
            scope_filename=filename,
            debug_retrieval=retrieval,
            citations=DurableCitations(turn_id, "plain", owner_id, conversation_id),
            full_debug=True,
        )
        request["prompt"] = json.dumps(
            {"canonical_history": history[-60:], "user_message": content, "evidence": evidence}
        )
        save_trace(
            owner_id,
            turn_id,
            "plain",
            folders,
            {
                "name": "knowledge_base_search",
                "conversation_id": conversation_id,
                "query": content,
                "effective_scope": {"user_id": owner_id, "folder_ids": folders},
                "status": "completed",
                "sources": retrieval,
            },
            evidence,
        )
    try:
        return (
            sb.rpc(
                "tsukai_begin_chat_turn",
                {
                    "p_turn_id": turn_id,
                    "p_owner_id": owner_id,
                    "p_conversation_id": conversation_id,
                    "p_request": request,
                    "p_content": content,
                },
            )
            .execute()
            .data
        )
    except Exception as exc:
        if getattr(exc, "code", None) == "23505":
            raise HTTPException(409, "Conversation already has an active turn") from None
        raise


def submit_turn(turn: dict) -> dict:
    turn = owned_turn(turn["owner_id"], turn_id=turn["id"])
    if turn.get("cancel_requested") and not turn.get("job_id"):
        get_supabase_thread_safe().table("tsukai_chat_turns").update({"state": "cancelled"}).eq(
            "id", turn["id"]
        ).execute()
        raise ExecutionError("cancelled")
    scope = turn_scope(turn)
    request = turn["request"]
    client = client_for(scope, request["operation"], request["profile"])
    try:
        # Retrying this exact accepted body recovers an admission response lost in transit.
        job_id = turn.get("job_id") or client.submit(request)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {400, 403, 409, 422}:
            get_supabase_thread_safe().table("tsukai_chat_turns").update(
                {
                    "state": "failed",
                    "error_code": "admission_rejected",
                }
            ).eq("id", turn["id"]).eq("state", "prepared").execute()
        raise
    finally:
        client.close()
    if not turn.get("job_id"):
        get_supabase_thread_safe().table("tsukai_chat_turns").update(
            {
                "job_id": job_id,
                "state": "submitted",
            }
        ).eq("id", turn["id"]).eq("owner_id", turn["owner_id"]).is_("job_id", "null").execute()
    current = owned_turn(turn["owner_id"], turn_id=turn["id"])
    if current.get("job_id") != job_id:
        raise ExecutionError("job_mapping_conflict")
    if current.get("cancel_requested"):
        cancellation_client = client_for(scope, request["operation"], request["profile"])
        try:
            cancellation_client.cancel(job_id)
        finally:
            cancellation_client.close()
    return current


def publish_turn(turn: dict, result, *, attempt_id: str | None = None) -> str:
    scope = turn_scope(turn)
    request = turn["request"]
    attempt_id = result.attempt_id or attempt_id
    if request["profile"] == "chat" and not attempt_id:
        raise ExecutionError("missing_attempt", "accepted evidence namespace unavailable")
    evidence_job = turn["id"] if request["profile"] == "completion" else turn["job_id"]
    traces = (
        get_supabase_thread_safe()
        .table("tsukai_tool_traces")
        .select("id,trace,attempt_id")
        .eq("job_id", evidence_job)
        .eq("owner_id", turn["owner_id"])
    )
    if attempt_id and request["profile"] != "completion":
        traces = traces.eq("attempt_id", attempt_id)
    rows = traces.order("created_at").execute().data or []
    citations = sources_for(
        evidence_job, "plain" if request["profile"] == "completion" else attempt_id
    )
    import re

    cited = {int(n) for n in re.findall(r"\[(\d+)\]", result.text)}
    available = {entry["number"] for entry in citations}
    if not cited.issubset(available):
        raise ExecutionError(
            "unverified_citation", "answer cites a source absent from accepted evidence"
        )
    usage_client = client_for(scope, request["operation"], request["profile"])
    try:
        timing_attempts = (
            record_job_usage(
                usage_client,
                scope,
                request["operation"],
                request["model"],
                turn["job_id"],
                source="chat",
            )
            or []
        )
    finally:
        usage_client.close()
    debug = {
        "reasoning": [],
        "tool_calls": [
            {
                **{key: value for key, value in row["trace"].items() if key != "sources"},
                "artifact_id": row["id"],
                "is_error": row["trace"].get("status") == "failed",
            }
            for row in rows
        ],
        "retrieval": [
            {**source, "content": source.get("content", "")[:1200]}
            for row in rows
            for source in row["trace"].get("sources", [])
        ],
        "execution": {
            "job_id": turn["job_id"],
            "turn_id": turn["id"],
            "attempt_id": attempt_id,
            "usage": result.usage,
            "timings": {
                "accepted_at": turn.get("created_at"),
                "attempts": [
                    {
                        key: attempt.get(key)
                        for key in (
                            "attempt_id",
                            "started_at",
                            "finished_at",
                            "first_event_at",
                            "first_text_at",
                            "queue_wait_seconds",
                            "elapsed_seconds",
                            "first_event_seconds",
                            "first_text_seconds",
                        )
                    }
                    for attempt in timing_attempts
                ],
                "clock": "server UTC; durations from observed runner events",
            },
        },
    }
    message_id = (
        get_supabase_thread_safe()
        .rpc(
            "tsukai_commit_chat_turn",
            {
                "p_turn_id": turn["id"],
                "p_owner_id": turn["owner_id"],
                "p_job_id": turn["job_id"],
                "p_content": result.text,
                "p_debug": debug,
                "p_citations": citations,
            },
        )
        .execute()
        .data
    )
    client = client_for(scope, request["operation"], request["profile"])
    try:
        get_supabase_thread_safe().table("tsukai_native_usage").update(
            {
                "message_id": message_id,
            }
        ).eq("job_id", turn["job_id"]).eq("owner_id", turn["owner_id"]).execute()
        client.acknowledge(turn["job_id"], "chat", str(message_id))
        get_supabase_thread_safe().table("tsukai_chat_turns").update(
            {
                "state": "acknowledged",
            }
        ).eq("id", turn["id"]).eq("owner_id", turn["owner_id"]).execute()
    except Exception as exc:
        logger.warning(
            "committed native answer acknowledgement deferred for %s (%s)",
            turn["id"],
            type(exc).__name__,
        )
    finally:
        client.close()
    return str(message_id)


def reconcile_turn(turn: dict):
    turn = submit_turn(turn)
    scope, request = turn_scope(turn), turn["request"]
    client = client_for(scope, request["operation"], request["profile"])
    try:
        status = client.status(turn["job_id"])
        if status["status"] == "completed":
            result = client.result(turn["job_id"])
            publish_turn(
                turn,
                result,
                attempt_id=(
                    status.get("attempt_id") or (status.get("result") or {}).get("attempt_id")
                ),
            )
        elif status["status"] in {"failed", "cancelled", "uncertain"}:
            record_job_usage(
                client, scope, request["operation"], request["model"], turn["job_id"], source="chat"
            )
            get_supabase_thread_safe().table("tsukai_chat_turns").update(
                {
                    "state": status["status"],
                    "error_code": (status.get("error") or {}).get("code", status["status"]),
                }
            ).eq("id", turn["id"]).eq("owner_id", turn["owner_id"]).execute()
    finally:
        client.close()


def reconcile_pending():
    rows = (
        get_supabase_thread_safe()
        .table("tsukai_chat_turns")
        .select("*")
        .in_("state", ["prepared", "submitted", "committed"])
        .order("updated_at")
        .limit(100)
        .execute()
        .data
        or []
    )
    for turn in rows:
        try:
            reconcile_turn(turn)
        except HTTPException as exc:
            if exc.status_code in {403, 404}:
                # Release the domain conversation lock before any remote cleanup.
                # Cancellation has its own durable retry loop; no new inference is admitted.
                get_supabase_thread_safe().table("tsukai_chat_turns").update(
                    {
                        "state": "failed",
                        "error_code": "scope_revoked",
                        "cancel_requested": bool(turn.get("job_id")),
                    }
                ).eq("id", turn["id"]).eq("owner_id", turn["owner_id"]).execute()
            else:
                logger.warning("native turn reconciliation deferred: %s", exc.status_code)
        except ExecutionError as exc:
            if exc.code in {
                "unverified_citation",
                "missing_attempt",
                "needs_input",
                "invalid_outcome",
            }:
                get_supabase_thread_safe().table("tsukai_chat_turns").update(
                    {
                        "state": "failed",
                        "error_code": exc.code,
                    }
                ).eq("id", turn["id"]).eq("owner_id", turn["owner_id"]).execute()
            logger.warning("native chat outcome blocked for turn %s: %s", turn["id"], exc.code)
        except Exception:
            logger.warning(
                "native chat reconciliation failed for turn %s", turn["id"], exc_info=True
            )


async def reconciliation_loop():
    while True:
        if os.getenv("TSUKAI_URL"):
            if os.getenv("TSUKAI_NATIVE_TASKS"):
                await asyncio.to_thread(reconcile_pending)
            try:
                from services.ai.deletions import reconcile_deletions

                await asyncio.to_thread(reconcile_deletions)
            except Exception:
                logger.warning("native deletion reconciliation deferred", exc_info=True)
        await asyncio.sleep(5)


def stream_turn(turn: dict, *, cursor: int = 0):
    """Subscriber only: durable worker completion never depends on this generator."""
    turn = submit_turn(turn)
    scope, request = turn_scope(turn), turn["request"]
    client = client_for(scope, request["operation"], request["profile"])
    yield "data: " + json.dumps({"job_id": turn["job_id"], "turn_id": turn["id"]}) + "\n\n"
    try:
        for event in client.events(turn["job_id"], cursor=cursor):
            kind, data = event["type"], event["data"]
            frame = {"job_id": turn["job_id"], "turn_id": turn["id"], "event_id": event["seq"]}
            if kind == "text.delta":
                frame["token"] = data.get("text", data.get("delta", ""))
                frame["stage"] = "generating"
            elif kind in {"job.completed", "replay.expired"}:
                result = client.result(turn["job_id"])
                message_id = publish_turn(turn, result, attempt_id=event.get("attempt_id"))
                saved = (
                    get_supabase_thread_safe()
                    .table("messages")
                    .select("debug,citations")
                    .eq("id", message_id)
                    .eq("conversation_id", turn["conversation_id"])
                    .single()
                    .execute()
                    .data
                )
                frame.update(
                    {
                        "replace": result.text,
                        "done": True,
                        "message_id": message_id,
                        "debug": saved.get("debug"),
                        "citations": saved.get("citations"),
                    }
                )
                yield "data: " + json.dumps(frame) + "\n\n"
                return
            elif kind in {"job.failed", "job.cancelled", "job.uncertain"}:
                frame.update({"error": data.get("error", kind), "done": True})
            else:
                stage, detail = {
                    "job.queued": ("thinking", "Queued for native execution"),
                    "attempt.started": ("thinking", "Starting a scoped native attempt"),
                    "tool.started": ("searching", f"Kioku tool: {data.get('name', 'retrieval')}"),
                    "retrieval.completed": ("analyzing", "Reading returned Kioku evidence"),
                    "tool.completed": ("analyzing", "Kioku tool completed"),
                    "attempt.failed": (
                        "thinking",
                        "Native attempt failed; checking recovery policy",
                    ),
                }.get(kind, ("thinking", "Native execution in progress"))
                frame.update({"stage": stage, "detail": detail, "progress": {"type": kind, **data}})
            yield "id: " + str(event["seq"]) + "\ndata: " + json.dumps(frame) + "\n\n"
    except Exception as exc:
        yield (
            "data: "
            + json.dumps({"error": str(exc), "job_id": turn["job_id"], "turn_id": turn["id"]})
            + "\n\n"
        )
    finally:
        client.close()


def wake_reconciliation():
    threading.Thread(target=reconcile_pending, daemon=True, name="tsukai-chat-reconcile").start()


def reconcile_revoked_cancellations():
    rows = (
        get_supabase_thread_safe()
        .table("tsukai_chat_turns")
        .select("*")
        .eq("state", "failed")
        .eq("error_code", "scope_revoked")
        .eq("cancel_requested", True)
        .limit(20)
        .execute()
        .data
        or []
    )
    for turn in rows:
        request = turn["request"]
        # Captured authority is used exclusively to CANCEL that exact old job.
        # It cannot authorize retrieval, publication, rebuilding or admission.
        scope = ExecutionScope(
            turn["owner_id"],
            tuple(request["folder_ids"]),
            tool_allowlist=tuple(request["tool_allowlist"]),
        )
        client = client_for(scope, request["operation"], request["profile"])
        try:
            client.cancel(turn["job_id"])
            get_supabase_thread_safe().table("tsukai_chat_turns").update(
                {
                    "cancel_requested": False,
                }
            ).eq("id", turn["id"]).eq("owner_id", turn["owner_id"]).execute()
        except Exception:
            logger.warning("revoked native cancellation deferred for turn %s", turn["id"])
        finally:
            client.close()


async def revoked_cancellation_loop():
    while True:
        if os.getenv("TSUKAI_URL"):
            try:
                await asyncio.to_thread(reconcile_revoked_cancellations)
            except Exception:
                logger.warning("revoked native cancellation scan deferred", exc_info=True)
        await asyncio.sleep(5)
