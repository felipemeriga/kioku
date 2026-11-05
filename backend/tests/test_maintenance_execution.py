"""Immutable preparation and server-verified publication with a fake runner."""

import hashlib
import json
from types import SimpleNamespace

import jwt
import pytest

from services.ai.client import ExecutionError, ExecutionResult
from services.maintenance import execution

CAPTURE_JOB_USAGE = execution.capture_job_usage


class DB:
    def __init__(self, rows=None):
        self.rows, self.calls = rows or {}, []

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data={"ok": True}))


class Query:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.one, self.payload = db, name, {}, False, None

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def is_(self, key, value):
        self.filters[key] = None if value == "null" else value
        return self

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    def single(self):
        self.one = True
        return self

    def upsert(self, payload, **_):
        self.payload = payload
        return self

    def update(self, payload):
        self.payload = payload
        return self

    def execute(self):
        rows = self.db.rows.setdefault(self.name, [])
        if self.payload:
            if self.filters:
                for row in rows:
                    if all(row.get(k) == v for k, v in self.filters.items()):
                        row.update(self.payload)
            else:
                rows.append(self.payload)
        selected = [r for r in rows if all(r.get(k) == v for k, v in self.filters.items())]
        return SimpleNamespace(data=selected[0] if self.one else selected)


@pytest.fixture
def configured(monkeypatch):
    for key, value in {
        "TSUKAI_URL": "https://runner.invalid",
        "TSUKAI_SERVICE_TOKEN": "test-token",
        "TSUKAI_CAPABILITY_KEY": "test-key-that-is-at-least-32-bytes-long",
        "TSUKAI_CREDENTIAL_OWNER_ID": "owner",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("TSUKAI_MIHARI_NATIVE", raising=False)
    monkeypatch.setattr(execution, "capture_job_usage", lambda *_: True)


def test_native_is_default_off_and_owner_only(configured, monkeypatch):
    assert execution.native_enabled("other") is False
    monkeypatch.setenv("TSUKAI_MIHARI_NATIVE", "true")
    assert execution.native_enabled("owner") is True
    assert execution.native_enabled("other") is False


def test_prepare_idempotent_request_bound_no_tools_no_resume(configured, monkeypatch):
    snapshot = {
        "operation": "activity",
        "input": {"head_sha": "a" * 40},
        "current": {},
        "expected_sections": {},
    }
    monkeypatch.setattr(execution, "capture", lambda *_: (snapshot, None))
    db = DB()
    first = execution.prepare(db, "owner", "folder", "activity", snapshot["input"])
    again = execution.prepare(db, "owner", "folder", "activity", snapshot["input"])
    assert first["preparation_id"] == again["preparation_id"]
    assert first["request"] == again["request"]
    request = first["request"]
    claims = jwt.decode(
        first["capability"],
        "test-key-that-is-at-least-32-bytes-long",
        algorithms=["HS256"],
        audience="tsukai",
    )
    expected = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert claims["request_sha256"] == expected
    assert (claims["owner_id"], claims["sub"], claims["folder_ids"]) == (
        "owner",
        "mihari",
        ["folder"],
    )
    assert claims["operations"] == ["mihari.activity"]
    assert request["conversation_id"] is None
    assert request["tool_allowlist"] == []
    assert request["max_turns"] == 6


def prepared_row():
    return {
        "id": "prep",
        "user_id": "owner",
        "folder_id": "folder",
        "request": {"immutable": "source"},
        "snapshot": {"operation": "activity", "current": {}, "input": {}, "expected_sections": {}},
    }


@pytest.mark.parametrize("failure", ["foreign_digest", "needs_input", "invalid_schema"])
def test_unpublishable_result_never_reaches_database(configured, monkeypatch, failure):
    row = prepared_row()
    db = DB({"maintenance_preparations": [row]})
    expected = hashlib.sha256(
        json.dumps(row["request"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(execution, "capability", lambda *_: "cap")
    monkeypatch.setattr(
        execution.httpx,
        "get",
        lambda *_a, **_k: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"request_sha256": "foreign" if failure == "foreign_digest" else expected},
        ),
    )

    class Runner:
        def __init__(self, *_):
            pass

        def close(self):
            pass

        def result(self, job):
            if failure == "needs_input":
                raise ExecutionError("needs_input")
            return ExecutionResult(job, "{}", {"arbitrary": "facts"}, {}, None)

        def acknowledge(self, *_):
            pytest.fail("invalid result was acknowledged")

    monkeypatch.setattr(execution, "TsukaiClient", Runner)
    with pytest.raises((ValueError, ExecutionError)):
        execution.publish(db, "owner", "folder", "prep", "job")
    assert db.calls == []


def test_foreign_owner_and_duplicate_job_binding(configured, monkeypatch):
    monkeypatch.setattr(execution, "acknowledge_publication", lambda *_: None)
    row = prepared_row()
    db = DB({"maintenance_preparations": [row]})
    with pytest.raises(PermissionError):
        execution.publish(db, "foreign", "folder", "prep", "job")
    row.update(execution_job_id="job", publication={"ok": True, "updated": False})
    assert execution.publish(db, "owner", "folder", "prep", "job") == row["publication"]
    with pytest.raises(ValueError):
        execution.publish(db, "owner", "folder", "prep", "another-job")


def test_quality_repair_is_a_new_bounded_session(configured, monkeypatch):
    snapshot = {
        "operation": "activity",
        "input": {"head_sha": "a" * 40},
        "current": {},
        "expected_sections": {},
    }
    monkeypatch.setattr(execution, "capture", lambda *_: (snapshot, None))
    db = DB()
    original = execution.prepare(db, "owner", "folder", "activity", snapshot["input"])
    db.rows["maintenance_preparations"][0]["validation_error"] = "activity failed quality check"
    repaired = execution.prepare(db, "owner", "folder", "activity", snapshot["input"])
    assert repaired["preparation_id"] != original["preparation_id"]
    assert repaired["request"]["idempotency_key"] != original["request"]["idempotency_key"]
    assert repaired["request"]["conversation_id"] is None
    assert repaired["request"]["tool_allowlist"] == []
    assert "independent attempt" in repaired["request"]["prompt"]
    assert (
        execution.prepare(db, "owner", "folder", "activity", snapshot["input"])["preparation_id"]
        == repaired["preparation_id"]
    )
    db.rows["maintenance_preparations"][1]["validation_error"] = "still invalid"
    with pytest.raises(ValueError, match="exhausted"):
        execution.prepare(db, "owner", "folder", "activity", snapshot["input"])


def test_publish_retries_lost_ack_without_result_fetch_or_second_database_apply(
    configured, monkeypatch
):
    row = prepared_row()
    db = DB({"maintenance_preparations": [row]})
    expected = hashlib.sha256(
        json.dumps(row["request"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(execution, "capability", lambda *_: "cap")
    monkeypatch.setattr(
        execution.httpx,
        "get",
        lambda *_a, **_k: SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: {"request_sha256": expected}
        ),
    )
    calls = {"result": 0, "apply": 0, "ack": 0}

    class Runner:
        def __init__(self, *_):
            pass

        def result(self, job):
            calls["result"] += 1
            return ExecutionResult(
                job,
                "",
                {"summary": "Accurate summary", "highlights": ["Verified change"]},
                {},
                None,
            )

        def acknowledge(self, *_):
            calls["ack"] += 1
            if calls["ack"] == 1:
                raise TimeoutError("runner acknowledgement timeout after commit")

        def close(self):
            pass

    def committed(*_):
        calls["apply"] += 1
        row.update(execution_job_id="job", publication={"ok": True, "updated": True})
        db.rows["maintenance_runner_ack_outbox"] = [
            {
                "preparation_id": "prep",
                "user_id": "owner",
                "folder_id": "folder",
                "job_id": "job",
                "acknowledged_at": None,
            }
        ]
        return row["publication"]

    monkeypatch.setattr(execution, "TsukaiClient", Runner)
    monkeypatch.setattr(execution, "apply_result", committed)
    with pytest.raises(TimeoutError):
        execution.publish(db, "owner", "folder", "prep", "job")
    assert db.rows["maintenance_runner_ack_outbox"][0]["acknowledged_at"] is None
    assert execution.publish(db, "owner", "folder", "prep", "job") == row["publication"]
    assert db.rows["maintenance_runner_ack_outbox"][0]["acknowledged_at"] is not None
    assert calls == {"result": 1, "apply": 1, "ack": 2}


def test_pending_ack_reconciles_even_when_prepare_skips_model(configured, monkeypatch):
    row = {**prepared_row(), "execution_job_id": "job", "publication": {"ok": True}}
    pending = {
        "preparation_id": "prep",
        "user_id": "owner",
        "folder_id": "folder",
        "job_id": "job",
        "acknowledged_at": None,
    }
    db = DB({"maintenance_preparations": [row], "maintenance_runner_ack_outbox": [pending]})
    monkeypatch.setattr(execution, "capture", lambda *_: (None, "no files"))
    acknowledgements = []

    def ack(sb, prepared, client=None):
        acknowledgements.append(prepared["execution_job_id"])
        pending["acknowledged_at"] = "confirmed"

    monkeypatch.setattr(execution, "acknowledge_publication", ack)
    assert (
        execution.prepare(db, "owner", "folder", "activity", {"head_sha": "a" * 40})["engine"]
        == "skip"
    )
    assert acknowledgements == ["job"]
    assert pending["acknowledged_at"] == "confirmed"


@pytest.mark.parametrize("copy_fails", [False, True])
def test_usage_outbox_copies_all_attempts_or_retains_pending_without_ack(
    configured, monkeypatch, copy_fails
):
    import sys

    row = {**prepared_row(), "execution_job_id": "job"}
    row["request"] = {"operation": "mihari.activity", "model": "claude-sonnet-4-6"}
    receipt = {
        "job_id": "job",
        "preparation_id": "prep",
        "user_id": "owner",
        "folder_id": "folder",
        "outcome": "completed",
        "captured_at": None,
    }
    db = DB(
        {
            "maintenance_usage_outbox": [receipt],
            "maintenance_runner_ack_outbox": [{"preparation_id": "prep", "user_id": "owner"}],
        }
    )
    monkeypatch.setattr(execution, "capture_job_usage", CAPTURE_JOB_USAGE)
    attempts = [
        {"attempt_id": "repair-1", "status": "failed", "usage": None},
        {"attempt_id": "repair-2", "status": "completed", "usage": {"complete": False}},
    ]
    copied, acknowledged = [], []

    def record(client, scope, operation, model, job_id, *, source):
        assert (scope.owner_id, scope.caller, operation, source) == (
            "owner",
            "mihari",
            "mihari.activity",
            "mihari",
        )
        if copy_fails:
            raise RuntimeError("product usage database unavailable")
        copied.extend(client.usage(job_id)["attempts"])

    monkeypatch.setitem(
        sys.modules, "services.ai.accounting", SimpleNamespace(record_job_usage=record)
    )
    runner = SimpleNamespace(
        usage=lambda _: {"attempts": attempts}, acknowledge=lambda *_: acknowledged.append(True)
    )
    execution.acknowledge_publication(db, row, runner)
    if copy_fails:
        assert receipt["captured_at"] is None
        assert acknowledged == []
    else:
        assert copied == attempts
        assert copied[0]["usage"] is None
        assert receipt["captured_at"] is not None
        assert acknowledged == [True]


def test_usage_receipt_persists_failed_jobs_without_domain_publication(configured):
    row = prepared_row()
    db = DB()
    execution.track_terminal_usage(db, row, "failed-job", "failed")
    assert db.rows["maintenance_usage_outbox"][0]["outcome"] == "failed"
    assert db.calls == []


def test_needs_input_job_still_copies_attempt_usage_without_applying_facts(configured, monkeypatch):
    import sys

    row = prepared_row()
    row["request"] = {"operation": "mihari.activity", "model": "claude-sonnet-4-6"}
    db = DB({"maintenance_preparations": [row]})
    copied = []
    monkeypatch.setattr(execution, "capture_job_usage", CAPTURE_JOB_USAGE)
    monkeypatch.setattr(execution, "capability", lambda *_: "cap")
    expected = hashlib.sha256(
        json.dumps(row["request"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(
        execution.httpx,
        "get",
        lambda *_a, **_k: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"request_sha256": expected, "status": "completed"},
        ),
    )

    class Runner:
        def __init__(self, *_):
            pass

        def result(self, _):
            raise ExecutionError("needs_input")

        def usage(self, _):
            return {
                "attempts": [
                    {"attempt_id": "repair-failed", "usage": None},
                    {"attempt_id": "needs-input", "usage": {"complete": False}},
                ]
            }

        def close(self):
            pass

        def acknowledge(self, *_):
            pytest.fail("needs-input domain publication was acknowledged")

    monkeypatch.setattr(execution, "TsukaiClient", Runner)
    monkeypatch.setitem(
        sys.modules,
        "services.ai.accounting",
        SimpleNamespace(
            record_job_usage=lambda client, _scope, _operation, _model, job, **_kwargs: (
                copied.extend(client.usage(job)["attempts"])
            )
        ),
    )
    with pytest.raises(ExecutionError, match="needs_input"):
        execution.publish(db, "owner", "folder", "prep", "job")
    assert len(copied) == 2
    assert copied[0]["usage"] is None
    assert copied[1]["usage"]["complete"] is False
    assert db.rows["maintenance_usage_outbox"][0]["captured_at"] is not None
    assert db.calls == []


def test_existing_absent_doc_pass_heals_before_head_gate_without_any_generation(
    configured, monkeypatch
):
    head = "a" * 40
    reviews = {"activity": {"head_sha": head}, "architecture": {"head_sha": head}}
    snapshot = {
        "expected_sections": {"activity": {}, "architecture": {}, "documentation": {}},
        "input": {},
    }
    db = DB(
        {
            "repo_freshness": [
                {"folder_id": "folder", "user_id": "owner", "section_reviews": reviews}
            ]
        }
    )
    inspected = []

    def acknowledge(sb, owner, folder, expected_head):
        assert (sb, owner, folder, expected_head) == (db, "owner", "folder", head)
        inspected.append(True)
        reviews["documentation"] = {"head_sha": head, "reason": "absent", "document_exists": False}

    monkeypatch.setattr(execution, "acknowledge_absent_documentation", acknowledge)
    monkeypatch.setattr(execution, "capture", lambda *_: (snapshot, None))
    monkeypatch.setattr(
        execution,
        "build_request",
        lambda *_: pytest.fail("already-current pass started another model request"),
    )
    assert (
        execution.prepare(db, "owner", "folder", "review_plan", {"head_sha": head})["engine"]
        == "skip"
    )
    assert inspected == [True]
    assert db.calls == []


def test_absent_document_prepare_inspects_without_starting_model(configured, monkeypatch):
    db = DB()
    monkeypatch.setattr(execution, "capture", lambda *_: (None, "no detailed documentation yet"))
    monkeypatch.setattr(
        execution, "build_request", lambda *_: pytest.fail("absent guide regenerated")
    )
    result = execution.prepare(db, "owner", "folder", "documentation", {"head_sha": "a" * 40})
    assert result["engine"] == "skip"
    assert result["reason"] == "no detailed documentation yet"
    assert db.calls == [
        (
            "acknowledge_absent_mihari_documentation",
            {"p_folder_id": "folder", "p_user_id": "owner", "p_head_sha": "a" * 40},
        )
    ]


def test_documentation_policy_changes_invalidate_pending_request_not_reviewed_heads(
    configured, monkeypatch
):
    from services.maintenance.operations import GUIDES

    snapshot = {
        "operation": "documentation",
        "input": {"head_sha": "a" * 40},
        "current": {"id": "doc", "content": "Existing guide"},
        "expected_sections": {"documentation": {"content": "Abstract"}},
        "documentation_revision": "doc",
    }
    monkeypatch.setattr(execution, "capture", lambda *_: (snapshot, None))
    db = DB()
    first = execution.prepare(db, "owner", "folder", "documentation", snapshot["input"])
    identical = execution.prepare(db, "owner", "folder", "documentation", snapshot["input"])
    assert first["preparation_id"] == identical["preparation_id"]
    old_request = json.loads(json.dumps(first["request"]))
    monkeypatch.setitem(
        GUIDES, "documentation", GUIDES["documentation"] + " Changed instruction policy."
    )
    changed = execution.prepare(db, "owner", "folder", "documentation", snapshot["input"])
    assert changed["preparation_id"] != first["preparation_id"]
    assert (
        changed["request"]["metadata"]["prompt_policy_sha256"]
        != old_request["metadata"]["prompt_policy_sha256"]
    )
    assert first["request"] == old_request
    assert len(db.rows["maintenance_preparations"]) == 2
    db.rows["repo_freshness"] = [
        {
            "folder_id": "folder",
            "user_id": "owner",
            "section_reviews": {"documentation": {"head_sha": "a" * 40}},
        }
    ]
    assert (
        execution.prepare(db, "owner", "folder", "documentation", snapshot["input"])["engine"]
        == "skip"
    )
    assert len(db.rows["maintenance_preparations"]) == 2


def test_documentation_policy_does_not_change_unrelated_operation_identity(configured, monkeypatch):
    from services.maintenance.operations import GUIDES

    snapshot = {
        "operation": "activity",
        "input": {"head_sha": "a" * 40},
        "current": {},
        "expected_sections": {},
    }
    monkeypatch.setattr(execution, "capture", lambda *_: (snapshot, None))
    db = DB()
    first = execution.prepare(db, "owner", "folder", "activity", snapshot["input"])
    monkeypatch.setitem(GUIDES, "documentation", "A different documentation policy")
    again = execution.prepare(db, "owner", "folder", "activity", snapshot["input"])
    assert again["preparation_id"] == first["preparation_id"]
    assert again["request"] == first["request"]
    assert "prompt_policy_sha256" in again["request"]["metadata"]


@pytest.fixture
def partial_pass(configured, monkeypatch):
    from copy import deepcopy

    head = "a" * 40
    payload = {
        "head_sha": head,
        "commits": ["change"],
        "changed_paths": ["worker.py"],
        "patch": "5 -> 10",
    }

    def section(value):
        return {
            "content": value,
            "provenance": "agent_mcp",
            "updated_by": "agent",
            "updated_at": "before",
        }

    initial = {
        "operation": "review_plan",
        "input": payload,
        "current": {
            "activity": {"summary": "old", "highlights": ["old"]},
            "overview": {"purpose": "app", "description": "old"},
        },
        "expected_sections": {
            "activity": section({"summary": "old", "highlights": ["old"]}),
            "overview": section({"purpose": "app", "description": "old"}),
        },
        "expected_reviews": {"activity": None, "overview": None},
        "documentation_revision": None,
    }
    state = {"snapshot": deepcopy(initial)}
    monkeypatch.setattr(execution, "capture", lambda *_: (deepcopy(state["snapshot"]), None))
    db = DB()
    plan = execution.prepare(db, "owner", "folder", "review_plan", payload)
    planrow = db.rows["maintenance_preparations"][0]
    planrow.update(
        execution_job_id="planner-job",
        publication={"selected": ["activity", "architecture", "overview"], "ok": True},
    )
    db.rows["maintenance_review_passes"] = [
        {
            "user_id": "owner",
            "folder_id": "folder",
            "head_sha": head,
            "preparation_id": planrow["id"],
        }
    ]
    activity = {"summary": "new change", "highlights": ["changed poll interval"]}
    db.rows["maintenance_preparations"].append(
        {
            "id": "activity-prep",
            "user_id": "owner",
            "folder_id": "folder",
            "head_sha": head,
            "operation": "activity",
            "snapshot": {"operation": "activity", "current": {}, "input": payload},
            "request": {"metadata": {"maintenance_operation": "activity"}},
            "execution_job_id": "activity-job",
            "publication": {"sections": ["activity"]},
        }
    )
    current = state["snapshot"]
    current["current"]["activity"] = activity
    current["expected_sections"]["activity"] = {
        "content": activity,
        "provenance": "auto",
        "updated_by": "mihari",
        "updated_at": "after",
    }
    current["expected_reviews"]["activity"] = {"head_sha": head, "reviewed_at": "after"}

    class Runner:
        def __init__(self, *_):
            pass

        def result(self, job):
            assert job == "activity-job"
            return ExecutionResult(job, "", activity, None, None)

        def close(self):
            pass

    monkeypatch.setattr(execution, "TsukaiClient", Runner)
    return db, state, payload, plan


def test_partial_publication_timeout_retry_keeps_original_plan_and_pending_reground(
    partial_pass, monkeypatch
):
    from copy import deepcopy

    db, state, payload, plan = partial_pass
    retry = execution.prepare(db, "owner", "folder", "review_plan", payload)
    assert retry["preparation_id"] == plan["preparation_id"]
    assert retry["request"] == plan["request"]
    assert db.rows["maintenance_preparations"][0]["publication"]["selected"] == [
        "activity",
        "architecture",
        "overview",
    ]
    pending = {
        "operation": "reground",
        "input": {
            "head_sha": payload["head_sha"],
            "selected": ["architecture", "overview"],
            "files": [{"path": "worker.py", "content": "code"}],
        },
        "current": {},
        "expected_sections": {},
        "expected_reviews": {},
        "symbols": [{"file": "z"}, {"file": "a"}],
        "edges": [{"src_node_id": "z"}, {"src_node_id": "a"}],
    }
    state["snapshot"] = deepcopy(pending)
    first = execution.prepare(db, "owner", "folder", "reground", pending["input"])
    # The worker timed out queued; runner admission retains the accepted job.
    jobs = {first["request"]["idempotency_key"]: "completed-unpublished-job"}
    state["snapshot"]["symbols"].reverse()
    state["snapshot"]["edges"].reverse()
    again = execution.prepare(db, "owner", "folder", "reground", pending["input"])
    assert again["preparation_id"] == first["preparation_id"]
    assert again["request"] == first["request"]
    assert jobs[again["request"]["idempotency_key"]] == "completed-unpublished-job"
    assert len(jobs) == 1


@pytest.mark.parametrize(
    "change",
    ["user_ui", "agent_mcp", "content", "head", "owner", "source", "policy", "documentation"],
)
def test_partial_plan_does_not_hide_external_edits_or_new_authority(
    partial_pass, monkeypatch, change
):
    from copy import deepcopy

    from services.maintenance.operations import GUIDES

    db, state, payload, plan = partial_pass
    payload = deepcopy(payload)
    owner = "owner"
    if change in ("user_ui", "agent_mcp"):
        state["snapshot"]["expected_sections"]["activity"]["provenance"] = change
    elif change == "content":
        state["snapshot"]["expected_sections"]["activity"]["content"] = {
            "summary": "external",
            "highlights": ["external"],
        }
    elif change == "head":
        payload["head_sha"] = "b" * 40
    elif change == "owner":
        owner = "other"
    elif change == "source":
        payload["patch"] = "different source"
    elif change == "policy":
        monkeypatch.setitem(GUIDES, "review_plan", GUIDES["review_plan"] + " New policy.")
    else:
        state["snapshot"]["documentation_revision"] = "external-document"
    state["snapshot"]["input"] = payload
    result = execution.prepare(db, owner, "folder", "review_plan", payload)
    assert result["preparation_id"] != plan["preparation_id"]


@pytest.mark.parametrize(
    "operation", ["activity", "reground", "review_plan", "documentation", "learnings"]
)
def test_formatter_budget_policy_changes_identity_without_mutating_accepted_work(
    configured, monkeypatch, operation
):
    from copy import deepcopy

    snapshot = {
        "operation": operation,
        "input": {"head_sha": "a" * 40, "selected": ["overview"], "new_entries": []},
        "current": {},
        "expected_sections": {},
    }
    if operation == "learnings":
        snapshot["input"]["new_entries"] = [{"id": "entry", "text": "Verified durable evidence."}]
        snapshot["current"] = []
    monkeypatch.setattr(execution, "capture", lambda *_: (snapshot, None))
    db = DB()
    monkeypatch.setattr(execution, "MAINTENANCE_MAX_TURNS", 3)
    old = execution.prepare(db, "owner", "folder", operation, snapshot["input"])
    immutable = deepcopy(old["request"])
    monkeypatch.setattr(execution, "MAINTENANCE_MAX_TURNS", 6)
    new = execution.prepare(db, "owner", "folder", operation, snapshot["input"])
    assert old["preparation_id"] != new["preparation_id"]
    assert old["request"] == immutable
    assert new["request"]["max_turns"] == 6
    assert new["request"]["max_turns"] > old["request"]["max_turns"]
    assert new["request"]["tool_allowlist"] == []
    assert new["request"]["conversation_id"] is None
    assert new["request"]["idempotency_key"] != immutable["idempotency_key"]
    assert (
        new["request"]["metadata"]["prompt_policy_sha256"]
        != immutable["metadata"]["prompt_policy_sha256"]
    )
    assert new["request"]["max_tokens"] == immutable["max_tokens"]
    assert new["request"]["response_schema"] == immutable["response_schema"]
    assert execution.request_matches_policy(db.rows["maintenance_preparations"][-1])
    assert not execution.request_matches_policy(db.rows["maintenance_preparations"][0])


def test_reground_source_change_cannot_reuse_graph_order_equivalent_preparation(
    configured, monkeypatch
):
    from copy import deepcopy

    snap = {
        "operation": "reground",
        "input": {"head_sha": "a" * 40, "selected": ["overview"]},
        "current": {},
        "expected_sections": {},
        "symbols": [],
        "edges": [],
    }
    monkeypatch.setattr(execution, "capture", lambda *_: (deepcopy(snap), None))
    db = DB()
    original = execution.prepare(db, "owner", "folder", "reground", snap["input"])
    snap["current"] = {"overview": {"purpose": "user edited", "description": "new"}}
    edited = execution.prepare(db, "owner", "folder", "reground", snap["input"])
    assert edited["preparation_id"] != original["preparation_id"]


def test_proof_transport_failure_never_falls_through_to_new_inference(partial_pass, monkeypatch):
    db, _, payload, _ = partial_pass
    before = len(db.rows["maintenance_preparations"])

    class Offline:
        def __init__(self, *_):
            pass

        def result(self, *_):
            raise TimeoutError("temporary read failure")

        def close(self):
            pass

    monkeypatch.setattr(execution, "TsukaiClient", Offline)
    with pytest.raises(TimeoutError):
        execution.prepare(db, "owner", "folder", "review_plan", payload)
    assert len(db.rows["maintenance_preparations"]) == before


@pytest.mark.parametrize("reverse", [False, True])
def test_graph_sampling_orders_all_projected_fields_before_limiting(monkeypatch, reverse):
    from services.maintenance.snapshots import capture

    monkeypatch.setattr(
        "services.folder_summary.repo.get_latest_summary",
        lambda *_: {"sections": {"overview": {"content": {"purpose": "app"}}}},
    )
    samples = {
        "repo_symbols": [
            {"file": f"f{i:03}", "symbol": "run", "kind": "function"} for i in range(110)
        ],
        "repo_edges": [
            {"ref_file": f"f{i:03}", "src_node_id": "a", "dst_node_id": "b", "relation": "calls"}
            for i in range(60)
        ],
    }
    if reverse:
        samples = {key: list(reversed(value)) for key, value in samples.items()}

    class Ordered(Query):
        def __init__(self, db, name):
            super().__init__(db, name)
            self.orders, self.bound = [], None

        def order(self, column):
            assert self.bound is None, "ORDER must precede LIMIT"
            self.orders.append(column)
            return self

        def limit(self, bound):
            self.bound = bound
            return self

        def execute(self):
            if self.name not in samples:
                return SimpleNamespace(data=[])
            assert set(self.orders) == set(samples[self.name][0])
            rows = sorted(samples[self.name], key=lambda row: tuple(row[k] for k in self.orders))
            return SimpleNamespace(data=rows[: self.bound])

    class GraphDB(DB):
        def table(self, name):
            return Ordered(self, name)

    snapshot, reason = capture(
        GraphDB(),
        "owner",
        "folder",
        "reground",
        {"head_sha": "a" * 40, "files": [{"path": "f000"}], "selected": ["overview"]},
    )
    assert reason is None
    assert len(snapshot["symbols"]) == 100
    assert snapshot["symbols"][0]["file"] == "f000"
    assert snapshot["symbols"][-1]["file"] == "f099"
    assert len(snapshot["edges"]) == 50
    assert snapshot["edges"][-1]["ref_file"] == "f049"


def test_fully_reviewed_pass_skips_without_fetching_expired_native_outputs(
    partial_pass, monkeypatch
):
    db, state, payload, _ = partial_pass
    reviews = {
        name: {"head_sha": payload["head_sha"]} for name in state["snapshot"]["expected_sections"]
    }
    db.rows["repo_freshness"] = [
        {"folder_id": "folder", "user_id": "owner", "section_reviews": reviews}
    ]
    monkeypatch.setattr(
        execution,
        "TsukaiClient",
        lambda *_: pytest.fail("fully reviewed HEAD must not fetch expired results"),
    )
    result = execution.prepare(db, "owner", "folder", "review_plan", payload)
    assert result["engine"] == "skip"
    assert result["reason"] == "HEAD already reviewed"


def test_original_plan_review_only_marker_keeps_same_partial_pass(partial_pass):
    db, state, payload, plan = partial_pass
    original = db.rows["maintenance_preparations"][0]
    unchanged = {
        "content": {"ci_cd_notes": "No deployment evidence"},
        "provenance": "agent_mcp",
        "updated_by": "agent",
        "updated_at": "before",
    }
    original["snapshot"]["expected_sections"]["deployment"] = unchanged
    original["snapshot"]["current"]["deployment"] = unchanged["content"]
    original["snapshot"]["expected_reviews"]["deployment"] = None
    # Rebuild the originally accepted request before simulating partial work.
    built = execution.build_request(original["snapshot"])
    original["request"]["prompt"] = built["prompt"]
    original["publication"]["reviewed"] = ["activity", "overview", "deployment"]
    state["snapshot"]["expected_sections"]["deployment"] = unchanged
    state["snapshot"]["current"]["deployment"] = unchanged["content"]
    state["snapshot"]["expected_reviews"]["deployment"] = {
        "head_sha": payload["head_sha"],
        "reviewed_at": "after",
    }
    result = execution.prepare(db, "owner", "folder", "review_plan", payload)
    assert result["preparation_id"] == plan["preparation_id"]
    assert result["request"] == original["request"]


def test_exact_proof_stops_after_required_sections_not_old_retained_jobs(partial_pass):
    from copy import deepcopy

    db, _, payload, plan = partial_pass
    published = deepcopy(db.rows["maintenance_preparations"][-1])
    db.rows["maintenance_preparations"].extend(
        [{**published, "id": f"old-{i}", "execution_job_id": "expired-old-job"} for i in range(20)]
    )
    # Fixture runner asserts only activity-job is fetched, never expired-old-job.
    result = execution.prepare(db, "owner", "folder", "review_plan", payload)
    assert result["preparation_id"] == plan["preparation_id"]


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        ("failed", "wall_timeout", True),
        ("failed", "native_error_max_turns", True),
        ("uncertain", "native_error_max_turns", False),
        ("running", "client_deadline", False),
        ("uncertain", "wall_timeout", False),
        ("failed", "reauth_required", False),
    ],
)
def test_only_confirmed_terminal_budget_exhaustion_enters_bounded_repair(
    configured, monkeypatch, status, code, retryable
):
    row = prepared_row()
    db = DB({"maintenance_preparations": [row]})
    expected = hashlib.sha256(
        json.dumps(row["request"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    monkeypatch.setattr(execution, "capability", lambda *_: "cap")
    monkeypatch.setattr(execution, "track_terminal_usage", lambda *_: None)
    monkeypatch.setattr(
        execution.httpx,
        "get",
        lambda *_a, **_k: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"request_sha256": expected, "status": status},
        ),
    )

    class Runner:
        def __init__(self, *_):
            pass

        def close(self):
            pass

        def result(self, _):
            raise ExecutionError(code)

    monkeypatch.setattr(execution, "TsukaiClient", Runner)
    with pytest.raises(ExecutionError):
        execution.publish(db, "owner", "folder", "prep", "job")
    assert bool(row.get("validation_error")) is retryable
    assert not row.get("publication")
    assert not row.get("execution_job_id")


def test_legacy_sql_review_areas_are_canonical_on_first_publication_and_replay(
    configured, monkeypatch
):
    from copy import deepcopy

    from fastapi.testclient import TestClient

    from main import app
    from routes import mihari
    from services.maintenance.operations import SECTIONS

    head = "a" * 40
    original = {
        "ok": True,
        "selected": ["activity", "documentation"],
        "reviewed": [
            "activity",
            "overview",
            "deployment",
            "how_it_runs",
            "preferences",
            "architecture",
            "dependencies",
            "documentation",
            "important_files",
            "activity",
        ],
    }
    immutable = deepcopy(original)

    class SQLDB(DB):
        def rpc(self, name, payload):
            assert name == "apply_maintenance_result"
            self.calls.append((name, payload))
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=original))

    row = {**prepared_row(), "execution_job_id": "job", "publication": original}
    state = {
        "user_id": "owner",
        "folder_id": "folder",
        "head_sha": head,
        "selected": ["activity", "documentation"],
        "acknowledged": ["activity", "documentation"],
    }
    db = SQLDB({"maintenance_preparations": [row], "maintenance_review_passes": [state]})
    projected = execution.apply_result(
        db, "prep", "owner", "job", {"selected": ["activity", "documentation"]}
    )
    assert projected["reviewed"] == list(SECTIONS)
    assert projected["selected"] == immutable["selected"]
    assert original == immutable
    monkeypatch.setattr(execution, "acknowledge_publication", lambda *_: None)
    monkeypatch.setattr(execution, "acknowledge_absent_documentation", lambda *_: None)
    monkeypatch.setattr(mihari, "_authorized_maintenance", lambda *_: ("owner", db))
    monkeypatch.setattr(mihari, "_api_key_auth", lambda *_: ("owner", "folder", "key"))
    monkeypatch.setattr(mihari, "get_supabase", lambda: db)
    monkeypatch.setattr("mcp_server._descendant_folder_ids", lambda *_: ["folder"])
    monkeypatch.setenv("TSUKAI_MIHARI_NATIVE", "true")
    client = TestClient(app)
    result = client.post(
        "/api/mihari/execution/publish",
        json={"folder_id": "folder", "preparation_id": "prep", "job_id": "job"},
    )
    assert result.status_code == 200
    assert result.json()["reviewed"] == list(SECTIONS)
    complete = {"folder_id": "folder", "head_sha": head, "reviewed": result.json()["reviewed"]}
    assert client.post("/api/mihari/review-complete", json=complete).status_code == 200
    # Canonicalizing a response must never satisfy missing publication ACKs.
    state["acknowledged"] = ["activity"]
    assert client.post("/api/mihari/review-complete", json=complete).status_code == 409
    state["acknowledged"] = ["activity", "documentation"]
    complete["head_sha"] = "b" * 40
    assert client.post("/api/mihari/review-complete", json=complete).status_code == 409
    assert original == immutable
    assert row["publication"]["reviewed"] == immutable["reviewed"]
