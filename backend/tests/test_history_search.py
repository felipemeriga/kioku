import json
from unittest.mock import MagicMock

import pytest

from services.history_search import compile_pattern, search_entries, search_history


def test_projection_excludes_capture_metadata():
    meta = {
        "id": "e1",
        "agent": "codex",
        "session_id": "native",
        "captured_at": "2026-11-04T23:02:00-03:00",
        "source_ref": "codex://native",
        "session_title": "Memory",
        "session_summary": "Cache retention.",
    }
    md = (
        "# Kioku agent journal — 2026-11-04\n\n## 23:02 — Codex\n"
        "<!-- kioku-entry: " + json.dumps(meta) + " -->\n\n- Fixed decoder.\n"
    )
    entry = search_entries(md)[0]
    assert entry["body"] == "- Fixed decoder."
    assert entry["session_id"] == "native"
    assert entry["title"] == "Memory"


def test_literal_modes():
    assert compile_pattern("a.*b", "phrase") == r"a\.\*b"
    assert compile_pattern("cache memory", "words") == "(?=.*cache)(?=.*memory).*"
    assert compile_pattern("", "words") == ""
    assert compile_pattern("SDK|cache", "regex") == "SDK|cache"


@pytest.mark.parametrize("pattern", ["[", "(a+)+$", r"(foo)\1", "x{900000}", "a**"])
def test_unsafe_regex_rejected(pattern):
    with pytest.raises(ValueError):
        compile_pattern(pattern, "regex")


@pytest.mark.parametrize(
    "options",
    [
        dict(fields="body"),
        dict(agent="other"),
        dict(timezone="invalid"),
        dict(date_from="2026-11-05", date_to="2026-11-04"),
    ],
)
def test_bad_filters_do_not_query(options):
    sb = MagicMock()
    with pytest.raises(ValueError):
        search_history(sb, "owner", "repo", **options)
    sb.rpc.assert_not_called()


def test_search_uses_owner_folder_all_dates_and_no_storage():
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = {"sessions": []}
    assert search_history(sb, "owner", "repo", q="decoder") == {"sessions": []}
    name, params = sb.rpc.call_args.args
    assert name == "search_agent_history"
    assert params["p_user_id"] == "owner" and params["p_folder_id"] == "repo"
    assert params["p_first"] is None and params["p_last"] is None
    sb.storage.from_.assert_not_called()


@pytest.mark.parametrize(
    "options",
    [
        {"q": "hello\nworld"},
        {"q": "x" * 161},
        {"mode": "semantic"},
        {"session_id": ""},
        {"session_id": "native/id"},
        {"session_id": "bad\x00id"},
        {"session_id": "x" * 257},
        {"date_from": "20261104"},
        {"date_from": "2026-02-30"},
        {"date_to": ""},
        {"timezone": "x" * 65},
        {"limit": 0},
        {"limit": 51},
        {"offset": -1},
        {"offset": 10001},
    ],
)
def test_all_form_fields_are_validated_before_rpc(options):
    sb = MagicMock()
    with pytest.raises(ValueError):
        search_history(sb, "owner", "repo", **options)
    sb.rpc.assert_not_called()


def test_native_session_identifier_is_trimmed_and_preserved():
    sb = MagicMock()
    search_history(sb, "owner", "repo", session_id="  01a.5_native:codex-id  ")
    assert sb.rpc.call_args.args[1]["p_session"] == "01a.5_native:codex-id"


@pytest.mark.parametrize(
    "params",
    [
        {"mode": "bad"},
        {"fields": "raw"},
        {"agent": "bad"},
        {"date_from": "20261104"},
        {"timezone": "Invalid/Zone"},
        {"session_id": "bad/id"},
        {"q": "a\nb"},
        {"limit": "51"},
        {"offset": "-1"},
    ],
)
def test_endpoint_rejects_invalid_form_fields(monkeypatch, params):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from auth import get_current_user
    from routes import learnings

    app = FastAPI()
    app.include_router(learnings.router)
    app.dependency_overrides[get_current_user] = lambda: "owner"
    sb = MagicMock()
    monkeypatch.setattr(learnings, "get_supabase_thread_safe", lambda: sb)
    monkeypatch.setattr(learnings, "_repo", lambda *args: None)
    response = TestClient(app).get("/api/folders/repo/history-search", params=params)
    assert response.status_code == 422
    sb.rpc.assert_not_called()
