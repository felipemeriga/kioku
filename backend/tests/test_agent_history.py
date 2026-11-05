"""Calendar transport bounds and opaque cursor scope."""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from services import agent_history

STORE = SimpleNamespace(sb=None, user_id="owner", folder_id="folder")


def test_calendar_dates_inclusive_and_empty_sessions(monkeypatch):
    calls = []
    monkeypatch.setattr(agent_history, "rpc", lambda *args: calls.append(args) or [])
    result = agent_history.days(STORE, date(2026, 3, 1), date(2026, 3, 31), "America/New_York")
    assert result == {"days": [], "timezone": "America/New_York"}
    assert calls[0][2]["p_from"] == "2026-03-01" and calls[0][2]["p_to"] == "2026-03-31"
    assert agent_history.sessions(STORE, date(2026, 3, 8))["sessions"] == []


@pytest.mark.parametrize(
    "start,end,tz,agent",
    [
        (date(2026, 1, 1), date(2026, 6, 1), "UTC", None),
        (date(2026, 2, 1), date(2026, 1, 1), "UTC", None),
        (date(2026, 1, 1), date(2026, 1, 2), "No/Such_Zone", None),
        (date(2026, 1, 1), date(2026, 1, 2), "UTC", "foreign"),
    ],
)
def test_calendar_invalid_bounds(start, end, tz, agent):
    with pytest.raises(HTTPException) as error:
        agent_history.days(STORE, start, end, tz, agent)
    assert error.value.status_code == 422


def test_calendar_cursor_binds_day_zone_owner_folder_agent(monkeypatch):
    rows = [
        {"id": "33333333-3333-4333-8333-333333333333", "day_last_event_at": "2026-03-08T07:00:00Z"}
    ] * 2
    monkeypatch.setattr(agent_history, "rpc", lambda *args: rows)
    cursor = agent_history.sessions(STORE, date(2026, 3, 8), limit=1)["next_cursor"]
    assert cursor
    for store, day, tz, agent in [
        (
            SimpleNamespace(sb=None, user_id="other", folder_id="folder"),
            date(2026, 3, 8),
            "UTC",
            None,
        ),
        (
            SimpleNamespace(sb=None, user_id="owner", folder_id="other"),
            date(2026, 3, 8),
            "UTC",
            None,
        ),
        (STORE, date(2026, 3, 9), "UTC", None),
        (STORE, date(2026, 3, 8), "America/New_York", None),
        (STORE, date(2026, 3, 8), "UTC", "codex"),
    ]:
        with pytest.raises(HTTPException):
            agent_history.sessions(store, day, tz, cursor, 1, agent)
    captured = []
    monkeypatch.setattr(agent_history, "rpc", lambda *args: captured.append(args[2]) or [])
    assert agent_history.sessions(STORE, date(2026, 3, 8), cursor=cursor, limit=1)["sessions"] == []
    assert captured[0]["p_before_at"] == rows[0]["day_last_event_at"]


def test_history_routes_auth_and_bounded_parameters(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes.agent_evidence as module

    monkeypatch.setattr(module, "_read_store", lambda *args: STORE)
    monkeypatch.setattr(agent_history, "rpc", lambda *args: [])
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[module.get_current_user] = lambda: "owner"
    client = TestClient(app)
    base = "/api/folders/folder/agent-history"
    assert client.get(
        base + "/days?start=2026-03-01&end=2026-03-31&timezone=America/New_York"
    ).json() == {
        "days": [],
        "timezone": "America/New_York",
    }
    assert client.get(base + "/sessions?date=2026-03-08&limit=50").json() == {
        "sessions": [],
        "next_cursor": None,
        "timezone": "UTC",
        "date": "2026-03-08",
    }
    assert client.get(base + "/sessions?date=2026-03-08&limit=101").status_code == 422
    assert client.get(base + "/days?start=2026-01-01&end=2026-12-01").status_code == 422
