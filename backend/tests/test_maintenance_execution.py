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

    def order(self, *_):
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
    assert request["max_turns"] == 1


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
