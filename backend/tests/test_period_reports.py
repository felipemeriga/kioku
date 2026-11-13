"""Calendar/citation/freshness contract for persisted period reports."""

import json
from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from routes.mihari import ReportRefreshRequest
from routes.reports import ReportSettings
from services.maintenance.operations import build_request, completion_schema, validate_result
from services.period_reports import (
    POLICY,
    calendar_period,
    capture_report,
    instants,
    iso,
    report_context,
    report_quote_choices,
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
    choices = report_quote_choices(snap["input"]["sources"])["journal:1"]
    assert quote["enum"] == [choice["id"] for choice in choices]
    assert all(choice["text"] in snap["input"]["sources"][0]["text"] for choice in choices)
    assert any("gap’s" in choice["text"] for choice in choices)
    _, result = report_fixture()
    result["sections"][0]["items"][0]["evidence_quote"] = choices[0]["id"]
    validated = validate_result(snap, result)
    assert validated["sections"][0]["items"][0]["evidence_quote"] == choices[0]["text"]
    snap["input"]["sources"].append({"id": "other", "text": "This is an uncited source excerpt."})
    result["sections"][0]["items"][0]["evidence_quote"] = report_quote_choices(
        snap["input"]["sources"]
    )["other"][0]["id"]
    normalized = validate_result(snap, result)
    assert normalized["sections"][0]["items"][0]["source_ids"][0] == "other"
    assert normalized["sections"][0]["items"][0]["evidence_quote"] == (
        "This is an uncited source excerpt."
    )
    assert "evidence_choices" in request["prompt"]


@pytest.mark.parametrize("zone", ["../../etc/passwd", "Mars/Olympus", "", "x" * 65])
def test_invalid_timezone_rejected_in_ui_and_maintenance(zone):
    with pytest.raises(ValidationError):
        ReportSettings(timezone=zone)
    with pytest.raises(ValidationError):
        ReportRefreshRequest(
            folder_id="11111111-1111-4111-8111-111111111111", head_sha="a" * 40, timezone=zone
        )


def test_maximum_report_quote_schema_fits_native_single_argument_budget():
    snap, _ = report_fixture()
    sources = []
    for prefix, count in (("journal:", 80), ("original:", 16), ("commit:", 150), ("pull:", 100)):
        for n in range(count):
            identifier = str(n) if prefix == "pull:" else f"{n:064x}"
            sources.append(
                {
                    "id": prefix + identifier,
                    "text": "\n".join(f"Exact source sentence number {j}." for j in range(6)),
                }
            )
    snap["input"]["sources"] = sources
    schema = completion_schema(build_request(snap)["schema"])
    assert len(json.dumps(schema).encode()) < 120000


class Query:
    def __init__(self, data):
        self.data = data

    def __getattr__(self, name):
        return lambda *a, **k: self

    def execute(self):
        return SimpleNamespace(data=self.data)

    def range(self, start, end):
        return Query(self.data[start : end + 1])


class DB:
    def __init__(self, entries, existing=None):
        self.entries, self.existing, self.calls = entries, existing or [], 0

    def table(self, name):
        assert name == "repo_period_reports"
        return Query(self.existing)

    def rpc(self, name, args):
        if name == "period_report_activity":
            periods = {}
            for row in self.entries:
                day = iso(row["captured_at"]).astimezone(ZoneInfo(args["p_timezone"])).date()
                for kind in ("weekly", "monthly"):
                    start, _ = calendar_period(kind, day)
                    key = (kind, start.isoformat())
                    period = periods.setdefault(
                        key, {"kind": kind, "period_start": key[1], "activity_signature": ""}
                    )
                    period["activity_signature"] += row["entry_id"] + row["body"]
            return Query(list(periods.values()))
        assert name == "period_report_source_snapshot"
        assert args["p_user"] == "owner" and args["p_folder"] == "repo"
        self.calls += 1
        entries = [
            row
            for row in self.entries
            if iso(args["p_after"]) <= iso(row["captured_at"]) < iso(args["p_before"])
        ]
        return Query(
            {
                "entries": entries,
                "events": [],
                "entry_count": len(entries),
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


def active_report_fixture():
    rows = [
        {
            "entry_id": "e",
            "session_id": "s",
            "agent": "codex",
            "captured_at": "2026-11-13T10:00:00Z",
            "body": "The earlier implementation was reverted.",
        }
    ]
    payload = {"head_sha": "a" * 40, "timezone": "UTC"}

    def saved(snapshot, hour):
        return {
            **snapshot["report"],
            "generated_at": f"2026-11-13T{hour}:01:00Z",
            "revision": 1,
            "content": {"title": "Review", "summary": "Recorded work."},
        }

    weekly, _ = capture_report(
        DB(rows), "owner", "repo", payload, datetime(2026, 11, 13, 11, tzinfo=timezone.utc)
    )
    week = saved(weekly, "11")
    monthly, _ = capture_report(
        DB(rows, [week]), "owner", "repo", payload, datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    )
    return rows, payload, week, saved(monthly, "12"), saved


def test_new_main_head_reviews_both_current_reports_despite_schedule_throttle():
    rows, payload, week, month, saved = active_report_fixture()
    payload["head_sha"] = "b" * 40
    weekly, _ = capture_report(
        DB(rows, [week, month]),
        "owner",
        "repo",
        payload,
        datetime(2026, 11, 13, 13, tzinfo=timezone.utc),
    )
    assert weekly["report"]["kind"] == "weekly"
    assert weekly["report"]["coverage"]["head_sha"] == "b" * 40
    assert weekly["report"]["source_digest"] != week["source_digest"]
    week = saved(weekly, "13")
    monthly, _ = capture_report(
        DB(rows, [week, month]),
        "owner",
        "repo",
        payload,
        datetime(2026, 11, 13, 14, tzinfo=timezone.utc),
    )
    assert monthly["report"]["kind"] == "monthly"
    assert monthly["report"]["coverage"]["head_sha"] == "b" * 40
    month = saved(monthly, "14")
    unchanged, _ = capture_report(
        DB(rows, [week, month]),
        "owner",
        "repo",
        payload,
        datetime(2026, 11, 13, 15, tzinfo=timezone.utc),
    )
    assert unchanged is None


def test_frequent_merges_prioritize_monthly_when_weekly_was_just_reviewed():
    rows, payload, week, month, saved = active_report_fixture()
    payload["head_sha"] = "b" * 40
    weekly, _ = capture_report(
        DB(rows, [week, month]),
        "owner",
        "repo",
        payload,
        datetime(2026, 11, 13, 13, tzinfo=timezone.utc),
    )
    week = saved(weekly, "13")
    payload["head_sha"] = "c" * 40
    next_review, _ = capture_report(
        DB(rows, [week, month]),
        "owner",
        "repo",
        payload,
        datetime(2026, 11, 13, 14, tzinfo=timezone.utc),
    )
    assert next_review["report"]["kind"] == "monthly"


def test_new_head_does_not_rebuild_completed_periods_with_identical_evidence():
    rows, payload, _, _, _ = active_report_fixture()
    month = {
        "kind": "monthly",
        "period_start": "2026-11-01",
        "generated_at": "2026-11-16T10:00:00Z",
        "coverage": {"policy": POLICY, "head_sha": payload["head_sha"]},
    }
    final, _ = capture_report(
        DB(rows, [month]), "owner", "repo", payload, datetime(2026, 11, 16, 11, tzinfo=timezone.utc)
    )
    assert final["report"]["kind"] == "weekly" and final["report"]["status"] == "final"
    previous = {
        **final["report"],
        "generated_at": "2026-11-16T11:01:00Z",
        "revision": 1,
        "content": {},
    }
    payload["head_sha"] = "b" * 40
    month["coverage"]["head_sha"] = payload["head_sha"]
    result, _ = capture_report(
        DB(rows, [month, previous]),
        "owner",
        "repo",
        payload,
        datetime(2026, 11, 16, 12, tzinfo=timezone.utc),
    )
    assert result is None


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


def test_backfill_discovers_all_active_weeks_without_empty_calendar_weeks():
    from services.period_reports import report_candidates

    rows = [
        {
            "entry_id": str(year),
            "session_id": "s",
            "agent": "codex",
            "captured_at": f"{year}-01-10T12:00:00Z",
            "body": "Recorded development work.",
        }
        for year in (2022, 2024, 2026)
    ]
    candidates, _ = report_candidates(
        DB(rows),
        "owner",
        "repo",
        {"head_sha": "a" * 40},
        datetime(2026, 11, 13, tzinfo=timezone.utc),
    )
    weeks = [candidate for candidate in candidates if candidate["kind"] == "weekly"]
    assert [week["period_start"] for week in weeks] == ["2026-01-05", "2024-01-08", "2022-01-10"]
    oldest, _ = capture_report(
        DB(rows),
        "owner",
        "repo",
        {"head_sha": "a" * 40, "report_kind": "weekly", "period_start": "2022-01-10"},
        datetime(2026, 11, 13, tzinfo=timezone.utc),
    )
    assert oldest["report"]["status"] == "final"
    assert oldest["input"]["sources"][0]["id"] == "journal:2022"


def test_report_metadata_pagination_does_not_forget_older_published_weeks():
    from services.period_reports import report_rows

    rows = [{"id": str(n)} for n in range(451)]
    result = report_rows(DB([], rows), "owner", "repo", "weekly", "UTC")
    assert len(result) == 451 and result[-1]["id"] == "450"


@pytest.mark.parametrize(
    "fields",
    [
        {"report_kind": "weekly"},
        {"report_kind": "yearly", "period_start": "2026-11-09"},
        {"report_kind": "weekly", "period_start": "2026-11-10"},
        {"report_kind": "monthly", "period_start": "2026-11-02"},
        {"head_at": "2026-11-13T10:00:00"},
    ],
)
def test_report_plan_rejects_invalid_or_incomplete_periods(fields):
    with pytest.raises(ValidationError):
        ReportRefreshRequest(
            folder_id="11111111-1111-4111-8111-111111111111", head_sha="a" * 40, **fields
        )


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


def test_legacy_worker_cannot_publish_new_principal_timeline_policy():
    snapshot, reason = capture_report(None, "owner", "repo", {"git_history_mode": "legacy"})
    assert snapshot is None
    assert "worker upgrade required" in reason


def test_snapshot_preserves_final_merge_fixes_beyond_the_commit_subject():
    message = "Commit on principal branch: tracking fixes (#484)\n\n" + "Earlier context. " * 35
    message += "Preserve recovery boundaries and clear cross-game tracking backlog."
    snapshot, _ = capture_report(
        DB([]),
        "owner",
        "repo",
        {
            "head_sha": "a" * 40,
            "timezone": "UTC",
            "commits": [{"sha": "a" * 40, "at": "2026-11-13T10:00:00Z", "text": message}],
        },
        datetime(2026, 11, 13, 11, tzinfo=timezone.utc),
    )
    assert snapshot["input"]["sources"][0]["text"] == message
