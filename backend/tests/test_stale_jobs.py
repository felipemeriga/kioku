"""Tests for the stale-ingestion-job reaper (is_job_stale + fail_stale_jobs)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.queue.jobs import STALE_JOB_MINUTES, fail_stale_jobs, is_job_stale


def _iso(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def test_fresh_running_job_is_not_stale():
    assert is_job_stale({"status": "running", "updated_at": _iso(1)}) is False


def test_old_running_job_is_stale():
    assert is_job_stale({"status": "running", "updated_at": _iso(STALE_JOB_MINUTES + 5)}) is True


def test_old_queued_job_is_stale():
    assert is_job_stale({"status": "queued", "updated_at": _iso(120)}) is True


def test_completed_and_failed_never_stale():
    assert is_job_stale({"status": "completed", "updated_at": _iso(9999)}) is False
    assert is_job_stale({"status": "failed", "updated_at": _iso(9999)}) is False


def test_falls_back_to_created_at():
    assert is_job_stale({"status": "queued", "created_at": _iso(120)}) is True


def test_missing_or_bad_timestamp_is_not_stale():
    assert is_job_stale({"status": "queued"}) is False
    assert is_job_stale({"status": "queued", "updated_at": "not-a-date"}) is False


def test_just_under_threshold_is_not_stale():
    assert is_job_stale({"status": "running", "updated_at": _iso(STALE_JOB_MINUTES - 1)}) is False


# ── fail_stale_jobs against a fake query builder ─────────────────────────
class _FakeQuery:
    def __init__(self, store):
        self.store = store

    def update(self, payload):
        self.store["payload"] = payload
        return self

    def in_(self, col, vals):
        self.store.setdefault("filters", []).append(("in", col, vals))
        return self

    def lt(self, col, val):
        self.store.setdefault("filters", []).append(("lt", col, val))
        return self

    def execute(self):
        return type("R", (), {"data": self.store.get("rows", [])})()


class _FakeSB:
    def __init__(self, rows):
        self.store = {"rows": rows}

    def table(self, name):
        return _FakeQuery(self.store)


def test_fail_stale_jobs_marks_failed_and_counts():
    sb = _FakeSB([{"id": "1"}, {"id": "2"}])
    n = fail_stale_jobs(sb, older_than_min=15, kinds=["notion_sync", "notion_page"])
    assert n == 2
    assert sb.store["payload"]["status"] == "failed"
    ops = [f[0] for f in sb.store["filters"]]
    cols = [f[1] for f in sb.store["filters"]]
    assert "lt" in ops and "updated_at" in cols  # staleness cutoff applied
    assert "kind" in cols  # kind filter applied when provided


def test_fail_stale_jobs_zero_when_none():
    sb = _FakeSB([])
    assert fail_stale_jobs(sb) == 0
