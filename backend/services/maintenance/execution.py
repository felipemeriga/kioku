"""Prepared native jobs and server-verified transactional publication."""

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import jwt

from services.ai.client import TsukaiClient
from services.ai.scope import ExecutionScope, sign_capability
from services.maintenance.operations import (
    build_request,
    completion_schema,
    digest,
    validate_result,
)
from services.maintenance.snapshots import capture


def native_enabled(owner):
    if os.getenv("TSUKAI_MIHARI_NATIVE", "").lower() not in ("1", "true"):
        return False
    return bool(os.getenv("TSUKAI_CREDENTIAL_OWNER_ID")) and owner == os.getenv(
        "TSUKAI_CREDENTIAL_OWNER_ID"
    )


def capability(owner, folder, request=None):
    scope = ExecutionScope(owner, (folder,), caller="mihari")
    token = sign_capability(
        scope,
        "mihari." + request["metadata"]["maintenance_operation"] if request else "mihari.publish",
        "completion",
        ttl=900,
    )
    if request:
        claims = jwt.decode(
            token, os.environ["TSUKAI_CAPABILITY_KEY"], algorithms=["HS256"], audience="tsukai"
        )
        # Bind the exact submitted JSON object, independently of HTTP whitespace.
        claims["request_sha256"] = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        token = jwt.encode(claims, os.environ["TSUKAI_CAPABILITY_KEY"], algorithm="HS256")
    return token


def promote_main_learnings(sb, owner, folder, payload):
    """Commit arrival is deterministic; it never needs another model call."""
    commits = payload.get("main_commits") or []
    if not commits:
        return 0
    rows = (
        sb.table("repo_learnings")
        .select("id,git_sha")
        .eq("user_id", owner)
        .eq("folder_id", folder)
        .eq("status", "reported")
        .limit(200)
        .execute()
        .data
        or []
    )
    updated = 0
    for row in rows:
        if row.get("git_sha") in commits:
            sb.table("repo_learnings").update(
                {
                    "status": "committed",
                    "reviewed_head_sha": payload["head_sha"],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", row["id"]).eq("user_id", owner).eq("folder_id", folder).eq(
                "status", "reported"
            ).execute()
            updated += 1
    return updated


def apply_result(sb, preparation, owner, job_id, value):
    """The only publication boundary: SQL checks revisions under the folder lock."""
    return (
        sb.rpc(
            "apply_maintenance_result",
            {
                "p_preparation": preparation,
                "p_user": owner,
                "p_job": job_id,
                "p_value": value,
            },
        )
        .execute()
        .data
    )


def capture_pending(sb, owner, folder, operation, payload):
    for _ in range(24):
        snapshot, reason = capture(sb, owner, folder, operation, payload)
        if snapshot is None or operation != "learnings" or snapshot["input"]["new_entries"]:
            return snapshot, reason
        # A same-day revision with no unseen entry IDs needs only a checkpoint
        # acknowledgement. No native/API session is started for an empty batch.
        key = digest(
            {"deterministic_learning_checkpoint": snapshot, "owner": owner, "folder": folder}
        )
        sb.table("maintenance_preparations").upsert(
            {
                "id": str(uuid4()),
                "user_id": owner,
                "folder_id": folder,
                "head_sha": payload["head_sha"],
                "operation": operation,
                "input_digest": digest(snapshot),
                "idempotency_key": key,
                "snapshot": snapshot,
                "request": {},
            },
            on_conflict="user_id,idempotency_key",
            ignore_duplicates=True,
        ).execute()
        row = (
            sb.table("maintenance_preparations")
            .select("id")
            .eq("user_id", owner)
            .eq("idempotency_key", key)
            .single()
            .execute()
            .data
        )
        apply_result(sb, row["id"], owner, "deterministic:" + key, {"updates": []})
    return None, "empty journal revisions acknowledged"


def prepare(sb, owner, folder, operation, payload):
    snapshot, reason = capture_pending(sb, owner, folder, operation, payload)
    if snapshot is None:
        promoted = (
            promote_main_learnings(sb, owner, folder, payload) if operation == "learnings" else 0
        )
        return {
            "ok": True,
            "engine": "skip",
            "updated": False,
            "reason": reason,
            "updated_learnings": promoted,
        }
    if operation != "learnings":
        freshness = (
            sb.table("repo_freshness")
            .select("section_reviews")
            .eq("folder_id", folder)
            .eq("user_id", owner)
            .limit(1)
            .execute()
            .data
            or []
        )
        reviews = freshness[0].get("section_reviews", {}) if freshness else {}
        targets = (
            list(snapshot["expected_sections"])
            if operation == "review_plan"
            else snapshot["input"].get("selected", [operation])
        )
        if targets and all(
            (reviews.get(name) or {}).get("head_sha") == payload["head_sha"] for name in targets
        ):
            return {
                "ok": True,
                "engine": "skip",
                "updated": False,
                "selected": [],
                "reviewed": [],
                "reason": "HEAD already reviewed",
            }
    built = build_request(snapshot)
    preparation = str(uuid4())
    key = digest({"owner": owner, "folder": folder, "snapshot": snapshot})
    request = {
        "schema_version": 1,
        "idempotency_key": "maintenance:" + key,
        "owner_id": owner,
        "caller": "mihari",
        "operation": "mihari." + operation,
        "profile": "completion",
        "prompt": built["prompt"],
        "system_prompt": built["system"]
        + (
            " Wrap operation data in the standardized completion envelope: "
            "schema_version=1, outcome, data, missing_inputs, failure, warnings. "
            "Use needs_input with missing field/reason if evidence is insufficient; "
            "do not ask questions."
        ),
        "model": "claude-sonnet-4-6",
        "max_tokens": built["max_tokens"],
        "max_turns": 1,
        "thinking_tokens": 0,
        "response_schema": completion_schema(built["schema"]),
        "conversation_id": None,
        "folder_ids": [folder],
        "tool_allowlist": [],
        "tool_capability_ref": None,
        "parent_job_id": None,
        "root_job_id": None,
        "ai_depth": 0,
        "metadata": {"maintenance_operation": operation, "input_digest": digest(snapshot)},
    }
    record = {
        "id": preparation,
        "user_id": owner,
        "folder_id": folder,
        "head_sha": payload["head_sha"],
        "operation": operation,
        "input_digest": digest(snapshot),
        "idempotency_key": key,
        "snapshot": snapshot,
        "request": request,
    }
    # Identical retries recover the existing immutable preparation, never replace it.
    existing = (
        sb.table("maintenance_preparations")
        .select("*")
        .eq("user_id", owner)
        .eq("idempotency_key", key)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        record = existing[0]
        if record.get("validation_error"):
            original = record
            key = digest({"repair_of": original["id"], "snapshot": snapshot})
            request["idempotency_key"] = "maintenance:" + key
            request["prompt"] += (
                "\nA previous independent attempt failed deterministic validation: "
                + original["validation_error"][:300]
                + ". Produce a complete corrected result using only the original evidence."
            )
            repaired = (
                sb.table("maintenance_preparations")
                .select("*")
                .eq("user_id", owner)
                .eq("idempotency_key", key)
                .limit(1)
                .execute()
                .data
                or []
            )
            if repaired:
                record = repaired[0]
                if record.get("validation_error"):
                    raise ValueError("maintenance validation repair exhausted")
            else:
                record = {
                    **original,
                    "id": preparation,
                    "idempotency_key": key,
                    "request": request,
                    "repair_of": original["id"],
                    "validation_error": None,
                    "execution_job_id": None,
                    "publication": None,
                }
                record.pop("created_at", None)
                sb.table("maintenance_preparations").upsert(
                    record, on_conflict="user_id,idempotency_key", ignore_duplicates=True
                ).execute()
                record = (
                    sb.table("maintenance_preparations")
                    .select("*")
                    .eq("user_id", owner)
                    .eq("idempotency_key", key)
                    .single()
                    .execute()
                    .data
                )
        request = record["request"]
    else:
        sb.table("maintenance_preparations").upsert(
            record, on_conflict="user_id,idempotency_key", ignore_duplicates=True
        ).execute()
        record = (
            sb.table("maintenance_preparations")
            .select("*")
            .eq("user_id", owner)
            .eq("idempotency_key", key)
            .single()
            .execute()
            .data
        )
    return {
        "ok": True,
        "engine": "tsukai",
        "preparation_id": record["id"],
        "request": request,
        "capability": capability(owner, folder, request),
        "url": os.environ["TSUKAI_URL"],
        "expires_at": int(time.time()) + 900,
    }


def publish(sb, owner, folder, preparation, job_id):
    rows = (
        sb.table("maintenance_preparations")
        .select("*")
        .eq("id", preparation)
        .eq("user_id", owner)
        .eq("folder_id", folder)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise PermissionError("unknown maintenance preparation")
    row = rows[0]
    if row.get("execution_job_id"):
        if row["execution_job_id"] != job_id:
            raise ValueError("preparation already has another execution")
        return row["publication"]
    client = TsukaiClient(
        os.environ["TSUKAI_URL"],
        os.environ["TSUKAI_SERVICE_TOKEN"],
        capability(owner, folder, row["request"]),
    )
    try:
        # Bind job to prepared input via the durable runner job record. Never
        # accept caller-supplied model text or a result from a different job.
        response = httpx.get(
            os.environ["TSUKAI_URL"].rstrip("/") + "/v1/jobs/" + job_id,
            headers={
                "Authorization": "Bearer " + os.environ["TSUKAI_SERVICE_TOKEN"],
                "X-Tsukai-Capability": capability(owner, folder, row["request"]),
            },
            timeout=30,
        )
        response.raise_for_status()
        job = response.json()
        expected_digest = hashlib.sha256(
            json.dumps(row["request"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if job.get("request_sha256") != expected_digest:
            raise ValueError("execution does not match immutable preparation")
        result = client.result(job_id)
        try:
            value = validate_result(
                row["snapshot"], result.structured if result.structured is not None else result.text
            )
        except ValueError as exc:
            sb.table("maintenance_preparations").update({"validation_error": str(exc)[:300]}).eq(
                "id", preparation
            ).eq("user_id", owner).execute()
            raise ValueError("invalid_result:" + str(exc)) from exc
        publication = apply_result(sb, preparation, owner, job_id, value)
        client.acknowledge(job_id, "mihari", "maintenance:" + preparation)
        return publication
    finally:
        client.close()


def execute_api(sb, owner, folder, operation, payload):
    """API-provider compatibility uses the same pure builder, validator and CAS."""
    from services.llm import Task, complete
    from services.usage_ledger import UsageAttribution

    promoted = 0
    snapshot, reason = capture_pending(sb, owner, folder, operation, payload)
    if snapshot is None:
        result = {"ok": True, "updated": False, "reason": reason}
        if operation == "learnings":
            result["updated_learnings"] = promote_main_learnings(sb, owner, folder, payload)
        return result
    captured_at = datetime.now(timezone.utc).isoformat()
    built = build_request(snapshot)
    if operation == "documentation":
        from services.llm import stream_complete
        from services.usage_ledger import save_usage, usage_row

        with stream_complete(
            task=Task(built["task"]),
            max_tokens=built["max_tokens"],
            system=built["system"],
            messages=[{"role": "user", "content": built["prompt"]}],
        ) as stream:
            text = "".join(stream.text_stream).strip()
            save_usage(
                [
                    usage_row(
                        stream.get_final_message(),
                        UsageAttribution(owner, "mihari", operation, folder),
                    )
                ]
            )
        try:
            raw = json.loads(text.removeprefix("```json").removesuffix("```").strip())
        except ValueError:
            raw = {"content": text.removeprefix("```markdown").removesuffix("```").strip()}
    else:
        response = complete(
            task=Task(built["task"]),
            max_tokens=built["max_tokens"],
            system=built["system"],
            messages=[{"role": "user", "content": built["prompt"]}],
            attribution=UsageAttribution(owner, "mihari", operation, folder),
        )
        text = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
        raw = text.removeprefix("```json").removesuffix("```").strip()
    value = validate_result(snapshot, raw)
    preparation = str(uuid4())
    sb.table("maintenance_preparations").insert(
        {
            "id": preparation,
            "user_id": owner,
            "folder_id": folder,
            "head_sha": payload["head_sha"],
            "operation": operation,
            "input_digest": digest(snapshot),
            "idempotency_key": "api:" + preparation,
            "created_at": captured_at,
            "snapshot": snapshot,
            "request": {},
        }
    ).execute()
    publication = apply_result(sb, preparation, owner, "api:" + preparation, value)
    if operation == "learnings":
        publication["updated_learnings"] = publication.get("updated_learnings", 0) + promoted
    return publication
