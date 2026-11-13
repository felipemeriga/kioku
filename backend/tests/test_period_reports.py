"""Calendar/citation/freshness contract for persisted period reports."""

from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from routes.mihari import ReportRefreshRequest
from routes.reports import ReportSettings
from services.maintenance.operations import build_request, validate_result
from services.period_reports import (
    POLICY,
    calendar_period,
    capture_report,
    instants,
    iso,
    report_context,
)


@pytest.mark.parametrize("fraction", ["", ".2", ".22", ".220", ".2201", ".22012", ".220123"])
@pytest.mark.parametrize("offset", ["Z", "+00:00", "-03:00"])
def test_postgrest_timestamp_precision_is_runtime_independent(fraction, offset):
    parsed = iso(f"2026-11-09T13:38:59{fraction}{offset}")
    assert parsed.microsecond == int((fraction[1:] or "0").ljust(6, "0"))
    assert parsed.tzinfo is not None


@pytest.mark.parametrize("value", ["invalid", "2026-11-09T13:38:59", "2026-13-09T13:38:59Z"])
def test_report_timestamp_rejects_invalid_or_naive_values(value):
    with pytest.raises(ValueError):
        iso(value)


def test_iso_week_crosses_year_and_month_ends_include_leap_day():
    assert calendar_period("weekly", date(2027, 1, 1)) == (date(2026, 12, 28), date(2027, 1, 3))
    assert calendar_period("monthly", date(2028, 2, 9)) == (date(2028, 2, 1), date(2028, 2, 29))
    with pytest.raises(ValueError):
        calendar_period("yearly", date.today())


def test_dst_period_uses_local_calendar_not_fixed_24_hour_days():
    start, end = instants(date(2026, 3, 2), date(2026, 3, 8), "America/New_York")
    assert (end - start).total_seconds() == 167 * 3600


def report_fixture():
    snapshot = {
        "operation": "reports",
        "input": {
            "sources": [
                {
                    "id": "journal:1",
                    "text": "A PR was opened; runtime deployment remains unverified.",
                }
            ]
        },
        "expected_sections": {},
    }
    result = {
        "title": "Lifecycle review",
        "summary": "A lifecycle change was proposed and remains unverified.",
        "summary_source_ids": ["journal:1"],
        "sections": [
            {
                "heading": "Still open",
                "items": [
                    {
                        "text": "The runtime outcome remains unverified.",
                        "source_ids": ["journal:1"],
                        "evidence_quote": "runtime deployment remains unverified",
                    }
                ],
            }
        ],
    }
    return snapshot, result


def test_report_cannot_invent_source_or_quote_or_publish_partial_envelope():
    snap, value = report_fixture()
    assert validate_result(snap, value) == value
    assert build_request(snap)["schema"]["additionalProperties"] is False
    for mutate in (
        lambda x: x.update(summary_source_ids=["another-user-secret"]),
        lambda x: x["sections"][0]["items"][0].update(
            evidence_quote="Everything was deployed successfully"
        ),
    ):
        bad = deepcopy(value)
        mutate(bad)
        with pytest.raises(ValueError):
            validate_result(snap, bad)
    with pytest.raises(ValueError, match="nonpublishable"):
        validate_result(
            snap, {"outcome": "needs_input", "data": value, "missing_inputs": ["source"]}
        )


def test_report_quotes_are_schema_constrained_without_changing_punctuation():
    snap, _ = report_fixture()
    snap["input"]["sources"][0]["text"] = "- Kept the gap’s clock.\n- Later reverted the change."
    request = build_request(snap)
    quote = request["schema"]["properties"]["sections"]["items"]["properties"]["items"]["items"][
        "properties"
    ]["evidence_quote"]
    assert "Kept the gap's clock." not in quote["enum"]
    assert all(value in snap["input"]["sources"][0]["text"] for value in quote["enum"])
    assert any("gap’s" in value for value in quote["enum"])
    assert "evidence_choices" in request["prompt"]


@pytest.mark.parametrize("zone", ["../../etc/passwd", "Mars/Olympus", "", "x" * 65])
def test_invalid_timezone_rejected_in_ui_and_maintenance(zone):
    with pytest.raises(ValidationError):
        ReportSettings(timezone=zone)
    with pytest.raises(ValidationError):
        ReportRefreshRequest(
            folder_id="11111111-1111-4111-8111-111111111111", head_sha="a" * 40, timezone=zone
        )


class Query:
    def __init__(self, data):
        self.data = data

    def __getattr__(self, name):
        return lambda *a, **k: self

    def execute(self):
        return SimpleNamespace(data=self.data)


class DB:
    def __init__(self, entries, existing=None):
        self.entries, self.existing, self.calls = entries, existing or [], 0

    def table(self, name):
        assert name == "repo_period_reports"
        return Query(self.existing)

    def rpc(self, name, args):
        assert name == "period_report_sources"
        assert args["p_user"] == "owner" and args["p_folder"] == "repo"
        self.calls += 1
        return Query(
            {
                "entries": self.entries,
                "events": [],
                "entry_count": len(self.entries),
                "event_count": 0,
            }
        )


def test_retries_preserve_identical_snapshot_and_successful_day_is_not_regenerated():
    rows = [
        {
            "entry_id": "e",
            "session_id": "s",
            "agent": "codex",
            "captured_at": "2026-11-13T10:00:00Z",
            "body": "A PR was opened, not deployed.",
        }
    ]
    db = DB(rows)
    body = {"head_sha": "a" * 40, "timezone": "UTC"}
    first, _ = capture_report(
        db, "owner", "repo", body, datetime(2026, 11, 13, 11, tzinfo=timezone.utc)
    )
    later, _ = capture_report(
        db, "owner", "repo", body, datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    )
    assert first == later
    assert first["report"]["status"] == "draft"
    assert first["report"]["coverage"]["policy"] == POLICY
    assert first["input"]["sources"][0]["observed_at"] == "2026-11-13T10:00:00+00:00"
    old = {
        **first["report"],
        "generated_at": "2026-11-13T11:01:00Z",
        "revision": 1,
        "content": {"title": "Earlier review", "summary": "A proposal is recorded."},
    }
    db = DB(rows, [old])
    # The first weekly period is skipped before querying its source objects.
    next_report, _ = capture_report(
        db, "owner", "repo", body, datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    )
    assert next_report["report"]["kind"] == "monthly"
    assert db.calls == 1
    old["coverage"] = {**old["coverage"], "policy": POLICY - 1}
    old["source_digest"] = "previous-policy-fingerprint"
    revised, _ = capture_report(
        DB(rows, [old]), "owner", "repo", body, datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    )
    assert revised["report"]["kind"] == "weekly"
    assert revised["report"]["expected_revision"] == 1


def test_same_day_reversal_keeps_precise_source_order():
    rows = [
        {
            "entry_id": "revert",
            "session_id": "s",
            "agent": "codex",
            "captured_at": "2026-11-13T15:00:00Z",
            "body": "Reverted the earlier change after a regression.",
        },
        {
            "entry_id": "implement",
            "session_id": "s",
            "agent": "codex",
            "captured_at": "2026-11-13T10:00:00Z",
            "body": "Implemented the new cache policy.",
        },
    ]
    snap, _ = capture_report(
        DB(rows),
        "owner",
        "repo",
        {"head_sha": "a" * 40},
        datetime(2026, 11, 13, 16, tzinfo=timezone.utc),
    )
    assert [source["id"] for source in snap["input"]["sources"]] == [
        "journal:implement",
        "journal:revert",
    ]


def test_report_context_is_optional_and_session_queries_do_not_load_reports():
    class Offline:
        def table(self, _):
            raise RuntimeError("database offline")

    assert (
        report_context(Offline(), "u", ["f"], "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z", "UTC")
        == []
    )
    assert report_context(None, "u", ["f"], "a", "b", "UTC", session="s") == []


def test_report_routes_validate_forms_and_hide_foreign_repository(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth import get_current_user
    from routes import reports as routes

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_current_user] = lambda: "owner"

    class Foreign:
        def table(self, name):
            assert name == "folders"
            return Query([])

    monkeypatch.setattr(routes, "get_supabase_thread_safe", lambda: Foreign())
    client = TestClient(app)
    folder = "11111111-1111-4111-8111-111111111111"
    assert client.get(f"/api/folders/{folder}/reports").status_code == 404
    assert client.get(f"/api/folders/{folder}/reports?kind=yearly").status_code == 422
    assert client.get(f"/api/folders/{folder}/reports?offset=-1").status_code == 422
    assert client.get(f"/api/folders/{folder}/reports?limit=101").status_code == 422
    assert client.get("/api/folders/not-a-uuid/reports").status_code == 422
    assert client.get(f"/api/folders/{folder}/reports/{folder}?revision=0").status_code == 422
    assert (
        client.put(
            f"/api/folders/{folder}/report-settings", json={"timezone": "invalid"}
        ).status_code
        == 422
    )
    assert (
        client.put(
            f"/api/folders/{folder}/report-settings", json={"timezone": "UTC", "user_id": "other"}
        ).status_code
        == 422
    )


def test_report_references_are_reauthorized_and_expansion_keeps_source_pages_bounded(monkeypatch):
    from fastapi import HTTPException

    from services import agent_memory
    from services.agent_memory import encode_reference, read_memory
    from services.period_reports import read_report_reference

    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "fixture-signing-key")
    ref = {
        "v": 1,
        "kind": "period_report",
        "owner": "owner",
        "folder": "repo",
        "report": "report-id",
        "revision": 1,
        "start": 0,
    }
    monkeypatch.setattr(
        agent_memory, "folders_in_scope", lambda *_: [{"id": "other-repo", "name": "Other"}]
    )
    with pytest.raises(HTTPException) as exc:
        read_memory(None, "owner", ["other-repo"], encode_reference(ref))
    assert exc.value.status_code == 404
    _, content = report_fixture()

    class Stored:
        def table(self, name):
            if name == "repo_period_reports":
                return Query(
                    [{"id": "report-id", "folder_id": "repo", "kind": "weekly", "timezone": "UTC"}]
                )
            return Query(
                [
                    {
                        "content": content,
                        "sources": [
                            {"id": str(i), "kind": "journal", "text": "x" * 3000} for i in range(30)
                        ],
                        "cutoff": "2026-11-13T10:00:00Z",
                        "generated_at": "2026-11-13T10:01:00Z",
                        "coverage": {},
                    }
                ]
            )

    value = read_report_reference(Stored(), "owner", ref, 1000)["period_reports"][0]
    assert len(value["sources"]) == 8
    assert max(len(s["text"]) for s in value["sources"]) <= 500
    assert value["next_sources_reference"]
