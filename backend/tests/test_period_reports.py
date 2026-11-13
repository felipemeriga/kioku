"""Calendar/citation/freshness contract for persisted period reports."""

from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from routes.mihari import ReportRefreshRequest
from routes.reports import ReportSettings
from services.maintenance.operations import build_request, validate_result
from services.period_reports import calendar_period, capture_report, instants, report_context


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
    old = {**first["report"], "generated_at": "2026-11-13T11:01:00Z", "revision": 1, "content": {}}
    db = DB(rows, [old])
    # The first weekly period is skipped before querying its source objects.
    next_report, _ = capture_report(
        db, "owner", "repo", body, datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    )
    assert next_report["report"]["kind"] == "monthly"
    assert db.calls == 1


def test_report_context_is_optional_and_session_queries_do_not_load_reports():
    class Offline:
        def table(self, _):
            raise RuntimeError("database offline")

    assert (
        report_context(Offline(), "u", ["f"], "2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z", "UTC")
        == []
    )
    assert report_context(None, "u", ["f"], "a", "b", "UTC", session="s") == []
