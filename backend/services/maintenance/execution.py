"""Prepared native jobs and server-verified transactional publication."""

import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import jwt

from services.ai.client import ExecutionError, TsukaiClient
from services.ai.scope import ExecutionScope, sign_capability
from services.maintenance.operations import (
    SECTIONS,
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


def publication_response(publication):
    """Project legacy SQL section keys onto the current six-area wire contract.

    SQL stores the original pass and ACK proof unchanged. Old summaries may
    still contain retired preferences/dependencies/important_files sections.
    """
    if "reviewed" not in publication:
        return publication
    return {
        **publication,
        "reviewed": [name for name in SECTIONS if name in publication["reviewed"]],
    }


def apply_result(sb, preparation, owner, job_id, value, operation=None):
    """The only publication boundary: SQL checks revisions under the folder lock."""
    publication = (
        sb.rpc(
            "apply_period_report_result" if operation == "reports" else "apply_maintenance_result",
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
    return publication_response(publication)


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


def track_terminal_usage(sb, row, job_id, outcome):
    if outcome in ("completed", "failed", "cancelled", "uncertain"):
        sb.table("maintenance_usage_outbox").upsert(
            {
                "job_id": job_id,
                "preparation_id": row["id"],
                "user_id": row["user_id"],
                "folder_id": row["folder_id"],
                "outcome": outcome,
            },
            on_conflict="job_id",
            ignore_duplicates=True,
        ).execute()


def capture_job_usage(sb, row, job_id, client):
    """Copy every native attempt; unknown counters remain explicitly unknown."""
    try:
        pending = (
            sb.table("maintenance_usage_outbox")
            .select("captured_at")
            .eq("job_id", job_id)
            .eq("user_id", row["user_id"])
            .limit(1)
            .execute()
            .data
            or []
        )
        if not pending:
            return False
        if pending[0].get("captured_at"):
            return True
        from services.ai.accounting import record_job_usage

        record_job_usage(
            client,
            ExecutionScope(row["user_id"], (row["folder_id"],), caller="mihari"),
            row["request"]["operation"],
            row["request"]["model"],
            job_id,
            source="mihari",
        )
        sb.table("maintenance_usage_outbox").update(
            {"captured_at": datetime.now(timezone.utc).isoformat()}
        ).eq("job_id", job_id).eq("user_id", row["user_id"]).execute()
        return True
    except Exception:
        logging.getLogger(__name__).warning(
            "Mihari native usage copy remains pending", exc_info=True
        )
        return False


def reconcile_usage(sb, owner, folder):
    pending = (
        sb.table("maintenance_usage_outbox")
        .select("preparation_id,job_id")
        .eq("user_id", owner)
        .eq("folder_id", folder)
        .is_("captured_at", "null")
        .order("created_at")
        .limit(10)
        .execute()
        .data
        or []
    )
    for item in pending:
        rows = (
            sb.table("maintenance_preparations")
            .select("*")
            .eq("id", item["preparation_id"])
            .eq("user_id", owner)
            .eq("folder_id", folder)
            .limit(1)
            .execute()
            .data
            or []
        )
        if not rows:
            continue
        row = rows[0]
        client = TsukaiClient(
            os.environ["TSUKAI_URL"],
            os.environ["TSUKAI_SERVICE_TOKEN"],
            capability(owner, folder, row["request"]),
        )
        try:
            capture_job_usage(sb, row, item["job_id"], client)
        finally:
            client.close()


def acknowledge_publication(sb, row, client=None):
    """Replay the idempotent runner ACK; publication remains committed on failure."""
    own_client = client is None
    if own_client:
        client = TsukaiClient(
            os.environ["TSUKAI_URL"],
            os.environ["TSUKAI_SERVICE_TOKEN"],
            capability(row["user_id"], row["folder_id"], row["request"]),
        )
    try:
        if not capture_job_usage(sb, row, row["execution_job_id"], client):
            return
        client.acknowledge(row["execution_job_id"], "mihari", "maintenance:" + row["id"])
        sb.table("maintenance_runner_ack_outbox").update(
            {"acknowledged_at": datetime.now(timezone.utc).isoformat()}
        ).eq("preparation_id", row["id"]).eq("user_id", row["user_id"]).execute()
    finally:
        if own_client:
            client.close()


def reconcile_acknowledgements(sb, owner, folder):
    """Bounded per-repo reconciliation also runs when HEAD needs no model work."""
    pending = (
        sb.table("maintenance_runner_ack_outbox")
        .select("preparation_id,job_id")
        .eq("user_id", owner)
        .eq("folder_id", folder)
        .is_("acknowledged_at", "null")
        .order("created_at")
        .limit(10)
        .execute()
        .data
        or []
    )
    for item in pending:
        rows = (
            sb.table("maintenance_preparations")
            .select("*")
            .eq("id", item["preparation_id"])
            .eq("user_id", owner)
            .eq("folder_id", folder)
            .limit(1)
            .execute()
            .data
            or []
        )
        if rows:
            try:
                acknowledge_publication(sb, rows[0])
            except Exception:
                logging.getLogger(__name__).warning(
                    "Mihari runner acknowledgement remains pending", exc_info=True
                )


def acknowledge_absent_documentation(sb, owner, folder, head):
    """Authoritative no-model inspection, constrained to an existing same-HEAD pass."""
    return (
        sb.rpc(
            "acknowledge_absent_mihari_documentation",
            {
                "p_folder_id": folder,
                "p_user_id": owner,
                "p_head_sha": head,
            },
        )
        .execute()
        .data
    )


MAINTENANCE_MODEL = "claude-sonnet-4-6"
# Native structured output consumes formatter turns in addition to synthesis.
# Keep the allowance finite; one backend validation repair remains the only retry.
MAINTENANCE_MAX_TURNS = 6


def completion_system(built):
    return built["system"] + (
        " Wrap operation data in the standardized completion envelope: "
        "schema_version=1, outcome, data, missing_inputs, failure, warnings. "
        "Use needs_input with missing field/reason if evidence is insufficient; "
        "do not ask questions. Use the internal StructuredOutput formatter directly "
        "when available, without a duplicate textual draft or preamble."
    )


def request_matches_policy(row):
    built, request = build_request(row["snapshot"]), row["request"]
    return (
        request["prompt"] == built["prompt"]
        and request["system_prompt"] == completion_system(built)
        and request["max_tokens"] == built["max_tokens"]
        and request["response_schema"] == completion_schema(built["schema"])
        and request["max_turns"] == MAINTENANCE_MAX_TURNS
        and request["model"] == MAINTENANCE_MODEL
        and request.get("reasoning_effort")
        == ("medium" if row["snapshot"]["operation"] == "reports" else None)
    )


def recover_review_plan(sb, owner, folder, payload, snapshot):
    """Resume the accepted pass across its own partial publications, not new edits."""
    passes = (
        sb.table("maintenance_review_passes")
        .select("preparation_id")
        .eq("user_id", owner)
        .eq("folder_id", folder)
        .eq("head_sha", payload["head_sha"])
        .limit(1)
        .execute()
        .data
        or []
    )
    if not passes:
        return None
    rows = (
        sb.table("maintenance_preparations")
        .select("*")
        .eq("id", passes[0]["preparation_id"])
        .eq("user_id", owner)
        .eq("folder_id", folder)
        .eq("head_sha", payload["head_sha"])
        .eq("operation", "review_plan")
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return None
    row = rows[0]
    old = row["snapshot"]
    if (
        old.get("input") != payload
        or not row.get("execution_job_id")
        or not row.get("publication")
        or row.get("validation_error")
    ):
        return None
    if not request_matches_policy(row):
        return None
    before, current = old.get("expected_sections", {}), snapshot["expected_sections"]
    if set(before) != set(current):
        return None
    changed = [name for name in before if before[name] != current[name]]
    reviews = snapshot.get("expected_reviews", {})
    old_reviews = old.get("expected_reviews", {})
    review_changes = [name for name in reviews if reviews[name] != old_reviews.get(name)]
    if not changed and not review_changes:
        return (
            row
            if old.get("documentation_revision") == snapshot.get("documentation_revision")
            else None
        )
    # Only the current accepted pass's own published work can explain drift.
    published = (
        sb.table("maintenance_preparations")
        .select("*")
        .eq("user_id", owner)
        .eq("folder_id", folder)
        .eq("head_sha", payload["head_sha"])
        .order("created_at", desc=True)
        .limit(30)
        .execute()
        .data
        or []
    )
    # A review-only marker does not change evidence. The original accepted plan
    # already inspected these exact unchanged section revisions.
    proven = {
        name
        for name in review_changes
        if name not in changed
        and name in row["publication"].get("reviewed", [])
        and (reviews.get(name) or {}).get("head_sha") == payload["head_sha"]
    }
    proof_reads = 0
    documentation_proven = old.get("documentation_revision") == snapshot.get(
        "documentation_revision"
    )
    for item in published:
        if set(changed + review_changes).issubset(proven) and documentation_proven:
            break
        names = (item.get("publication") or {}).get("sections", [])
        needed = (set(names) & set(changed + review_changes)) - proven
        if (
            not needed
            or not item.get("execution_job_id")
            or item.get("validation_error")
            or item.get("created_at", "") < row.get("created_at", "")
        ):
            continue
        if any(
            (current[name] or {}).get("provenance") != "auto"
            or (current[name] or {}).get("updated_by") != "mihari"
            or (reviews.get(name) or {}).get("head_sha") != payload["head_sha"]
            for name in needed
            if name in changed
        ):
            continue
        if proof_reads >= 6:
            return None
        proof_reads += 1
        client = TsukaiClient(
            os.environ["TSUKAI_URL"],
            os.environ["TSUKAI_SERVICE_TOKEN"],
            capability(owner, folder, item["request"]),
        )
        try:
            result = client.result(item["execution_job_id"])
            value = validate_result(
                item["snapshot"],
                result.structured if result.structured is not None else result.text,
            )
        finally:
            client.close()
        op = item["operation"]
        outputs = value if op == "reground" else {op: value}
        for name in needed:
            if name == "documentation":
                # Full document revision and body must agree, not just its abstract.
                docs = (
                    sb.table("repo_documentation")
                    .select("id,content")
                    .eq("user_id", owner)
                    .eq("folder_id", folder)
                    .eq("id", snapshot.get("documentation_revision"))
                    .limit(1)
                    .execute()
                    .data
                    or []
                )
                if docs and docs[0]["content"] == value.get("content"):
                    documentation_proven = True
                    proven.add(name)
            elif name in outputs and (current[name] or {}).get("content") == outputs[name]:
                proven.add(name)
    if set(changed + review_changes).issubset(proven) and documentation_proven:
        return row
    return None


def recover_ordered_preparation(sb, owner, folder, operation, snapshot):
    """Legacy graph rows had no ORDER BY; their immutable prompt is still valid."""
    if operation != "reground":
        return None

    def normalized(value):
        return {
            **value,
            **{key: sorted(value.get(key, []), key=digest) for key in ("symbols", "edges")},
        }

    rows = (
        sb.table("maintenance_preparations")
        .select("*")
        .eq("user_id", owner)
        .eq("folder_id", folder)
        .eq("head_sha", snapshot["input"]["head_sha"])
        .eq("operation", operation)
        .order("created_at", desc=True)
        .limit(30)
        .execute()
        .data
        or []
    )
    for row in rows:
        if row.get("validation_error") or normalized(row["snapshot"]) != normalized(snapshot):
            continue
        if request_matches_policy(row):
            return row
    return None


def prepared_response(owner, folder, record):
    request = record["request"]
    return {
        "ok": True,
        "engine": "tsukai",
        "preparation_id": record["id"],
        "request": request,
        "capability": capability(owner, folder, request),
        "url": os.environ["TSUKAI_URL"],
        "expires_at": int(time.time()) + 900,
    }


def report_repair_snapshot(sb, owner, folder, operation, payload, preparation):
    """Keep a bounded correction on its original evidence despite concurrent arrivals."""
    rows = (
        sb.table("maintenance_preparations")
        .select("*")
        .eq("id", preparation)
        .eq("user_id", owner)
        .eq("folder_id", folder)
        .eq("operation", operation)
        .eq("head_sha", payload["head_sha"])
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows or operation != "reports":
        raise ValueError("Unknown report recovery preparation")
    row = rows[0]
    if row.get("repair_of") or not row.get("validation_error") or row.get("publication"):
        raise ValueError("Report recovery requires an unrepaired rejected preparation")
    if not request_matches_policy(row):
        raise ValueError("Report recovery policy changed; prepare a fresh report")
    snapshot = row["snapshot"]
    for supplied, stored in (
        ("report_kind", "kind"),
        ("period_start", "period_start"),
        ("timezone", "timezone"),
    ):
        if payload.get(supplied) is not None and payload[supplied] != snapshot["input"].get(stored):
            raise ValueError("Report recovery period does not match its preparation")
    return snapshot


def prepare(sb, owner, folder, operation, payload, retry_preparation_id=None):
    reconcile_usage(sb, owner, folder)
    reconcile_acknowledgements(sb, owner, folder)
    if operation == "documentation":
        acknowledge_absent_documentation(sb, owner, folder, payload["head_sha"])
    if retry_preparation_id:
        snapshot = report_repair_snapshot(
            sb, owner, folder, operation, payload, retry_preparation_id
        )
        reason = None
    else:
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
    if operation not in ("learnings", "reports"):
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
    if operation == "review_plan":
        recovered = recover_review_plan(sb, owner, folder, payload, snapshot)
        if recovered:
            return prepared_response(owner, folder, recovered)
    recovered = recover_ordered_preparation(sb, owner, folder, operation, snapshot)
    if recovered:
        return prepared_response(owner, folder, recovered)
    built = build_request(snapshot)
    preparation = str(uuid4())
    identity = {"owner": owner, "folder": folder, "snapshot": snapshot}
    # Transport/formatter policy is part of every operation's immutable identity.
    reasoning = {"reasoning_effort": "medium"} if operation == "reports" else {}
    identity["prompt_policy_sha256"] = digest(
        {
            "built": built,
            "system": completion_system(built),
            "schema": completion_schema(built["schema"]),
            "model": MAINTENANCE_MODEL,
            "max_turns": MAINTENANCE_MAX_TURNS,
            **reasoning,
        }
    )
    key = digest(identity)
    request = {
        "schema_version": 1,
        "idempotency_key": "maintenance:" + key,
        "owner_id": owner,
        "caller": "mihari",
        "operation": "mihari." + operation,
        "profile": "completion",
        "prompt": built["prompt"],
        "system_prompt": completion_system(built),
        "model": MAINTENANCE_MODEL,
        "max_tokens": built["max_tokens"],
        "max_turns": MAINTENANCE_MAX_TURNS,
        "thinking_tokens": 0,
        **reasoning,
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
    request["metadata"]["prompt_policy_sha256"] = identity["prompt_policy_sha256"]
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
                + original["validation_error"][: (1200 if operation == "reports" else 300)]
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
    return prepared_response(owner, folder, record)


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
        acknowledge_publication(sb, row)
        return publication_response(row["publication"])
    client = TsukaiClient(
        os.environ["TSUKAI_URL"],
        os.environ["TSUKAI_SERVICE_TOKEN"],
        capability(owner, folder, row["request"]),
    )
    verified = False
    published = False
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
        track_terminal_usage(sb, row, job_id, job.get("status"))
        verified = True
        try:
            result = client.result(job_id)
        except ExecutionError as exc:
            # Confirmed terminal budget exhaustion cannot be recovered by polling the
            # same immutable failed job. Reuse the existing single repair budget.
            # Never retry active, uncertain, cancelled or auth-failed executions.
            if job.get("status") == "failed" and exc.code in {
                "wall_timeout",
                "native_error_max_turns",
            }:
                sb.table("maintenance_preparations").update(
                    {"validation_error": f"execution {exc.code}; return a concise complete result"}
                ).eq("id", preparation).eq("user_id", owner).execute()
            raise
        try:
            value = validate_result(
                row["snapshot"], result.structured if result.structured is not None else result.text
            )
        except ValueError as exc:
            sb.table("maintenance_preparations").update(
                {
                    "validation_error": str(exc)[
                        : (1200 if row["snapshot"]["operation"] == "reports" else 300)
                    ]
                }
            ).eq("id", preparation).eq("user_id", owner).execute()
            raise ValueError("invalid_result:" + str(exc)) from exc
        publication = apply_result(sb, preparation, owner, job_id, value, row.get("operation"))
        published = True
        acknowledge_publication(sb, {**row, "execution_job_id": job_id}, client)
        return publication
    finally:
        if verified and not published:
            capture_job_usage(sb, row, job_id, client)
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
    publication = apply_result(sb, preparation, owner, "api:" + preparation, value, operation)
    if operation == "learnings":
        publication["updated_learnings"] = publication.get("updated_learnings", 0) + promoted
    return publication
