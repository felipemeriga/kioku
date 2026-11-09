"""Temporal authority and original evidence expansion, not just mocked search ranking."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from services.agent_memory import (
    bounds,
    encode_reference,
    folders_in_scope,
    read_memory,
    search_memory,
)
from services.agent_memory_index import chunks_for_event

OWNER = "11111111-1111-4111-8111-111111111111"
ROOT = "22222222-2222-4222-8222-222222222220"
FOLDER = "22222222-2222-4222-8222-222222222222"
SIBLING = "22222222-2222-4222-8222-222222222223"
SESSION = "33333333-3333-4333-8333-333333333333"


class Query:
    def __init__(self, rows):
        self.rows = list(rows)
        self.one = False
        self.maximum = None

    def select(self, *_):
        return self

    def eq(self, k, v):
        self.rows = [r for r in self.rows if r.get(k) == v]
        return self

    def in_(self, k, v):
        self.rows = [r for r in self.rows if r.get(k) in v]
        return self

    def gte(self, k, v):
        self.rows = [r for r in self.rows if r.get(k) is not None and r[k] >= v]
        return self

    def lt(self, k, v):
        self.rows = [r for r in self.rows if r.get(k) is not None and r[k] < v]
        return self

    def gt(self, k, v):
        self.rows = [r for r in self.rows if r.get(k) is not None and r[k] > v]
        return self

    def order(self, k, desc=False):
        self.rows.sort(key=lambda r: r.get(k) or "", reverse=desc)
        return self

    def limit(self, v):
        self.maximum = v
        return self

    @property
    def not_(self):
        self.negated = True
        return self

    def is_(self, key, value):
        if getattr(self, "negated", False):
            self.rows = [r for r in self.rows if r.get(key) is not None]
        else:
            self.rows = [r for r in self.rows if r.get(key) is None]
        return self

    def single(self):
        self.one = True
        return self

    def execute(self):
        rows = self.rows[: self.maximum] if self.maximum is not None else self.rows
        return SimpleNamespace(data=rows[0] if self.one else rows)


class Database:
    def __init__(self):
        self.rows = {
            "folders": [
                {"id": ROOT, "user_id": OWNER, "name": "root", "kind": "folder", "parent_id": None},
                {"id": FOLDER, "user_id": OWNER, "name": "repo", "kind": "repo", "parent_id": ROOT},
                {
                    "id": SIBLING,
                    "user_id": OWNER,
                    "name": "sibling",
                    "kind": "repo",
                    "parent_id": ROOT,
                },
                {
                    "id": "foreign",
                    "user_id": "another-owner",
                    "name": "repo",
                    "kind": "repo",
                    "parent_id": ROOT,
                },
            ]
        }

    def table(self, name):
        return Query(self.rows.get(name, []))


def test_root_scope_can_narrow_without_expanding_authority():
    sb = Database()
    assert {r["id"] for r in folders_in_scope(sb, OWNER, [ROOT, FOLDER, SIBLING], "root")} == {
        ROOT,
        FOLDER,
        SIBLING,
    }
    assert [r["id"] for r in folders_in_scope(sb, OWNER, [ROOT, FOLDER, SIBLING], "repo")] == [
        FOLDER
    ]
    with pytest.raises(HTTPException):
        folders_in_scope(sb, OWNER, [FOLDER], "sibling")
    assert folders_in_scope(sb, OWNER, []) == []


def test_duplicate_repo_names_are_not_silently_chosen():
    sb = Database()
    sb.rows["folders"][2]["name"] = "repo"
    with pytest.raises(HTTPException) as err:
        folders_in_scope(sb, OWNER, [FOLDER, SIBLING], "repo")
    assert err.value.status_code == 404


def test_local_day_and_asof_boundaries_are_enforced():
    assert bounds("2026-11-05", "2026-11-05", tz="America/Sao_Paulo") == (
        "2026-11-05T03:00:00+00:00",
        "2026-11-06T03:00:00+00:00",
    )
    assert bounds(as_of="2026-11-05T12:00:00-03:00")[1] == "2026-11-05T15:00:00.000001+00:00"
    start, end = bounds("2026-11-01", "2026-11-01", tz="America/New_York")
    from datetime import datetime

    assert (
        datetime.fromisoformat(end) - datetime.fromisoformat(start)
    ).total_seconds() == 25 * 3600


@pytest.mark.parametrize(
    "kwargs",
    [
        {"from_date": "2026-02-30"},
        {"tz": "not/a/zone"},
        {"from_date": "2026-11-08", "through_date": "2026-11-01"},
        {"as_of": "2026-11-05T12:00:00"},
        {"query": "bad\ninput"},
        {"limit": True},
        {"offset": -1},
        {"queries": ["x"] * 9},
        {"session": "a%*"},
        {"order": "random"},
    ],
)
def test_invalid_inputs_fail_before_provider_search(kwargs):
    with pytest.raises(HTTPException):
        search_memory(Database(), OWNER, [FOLDER], **kwargs)


def archive():
    sb = Database()
    records = [
        {
            "timestamp": "2026-11-05T23:00:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "call_id": "pair",
                "name": "exec",
                "arguments": "GOMEMLIMIT=3GiB",
            },
        },
        {
            "timestamp": "2026-11-06T04:00:00+00:00",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "call_id": "pair",
                "output": "future result",
            },
        },
    ]
    raw = b""
    events = []
    for i, record in enumerate(records, 1):
        line = (json.dumps(record) + "\n").encode()
        events.append(
            {
                "user_id": OWNER,
                "folder_id": FOLDER,
                "session_id": SESSION,
                "event_id": str(i) * 64,
                "object_id": "segment",
                "byte_offset": len(raw),
                "byte_length": len(line),
                "event_at": record["timestamp"],
                "record_sequence": i,
                "stream_id": "native",
                "generation": 1,
                "role": "tool",
                "event_type": "tool_call" if i == 1 else "tool_result",
                "displayable": True,
                "inherited": False,
                "call_id": "pair",
                "source_truncated": False,
            }
        )
        raw += line
    sb.rows["agent_evidence_sessions"] = [
        {
            "id": SESSION,
            "user_id": OWNER,
            "folder_id": FOLDER,
            "agent": "codex",
            "native_session_id": "native",
            "deleted_at": None,
        }
    ]
    sb.rows["agent_evidence_events"] = events
    sb.rows["agent_evidence_objects"] = [
        {
            "session_id": SESSION,
            "user_id": OWNER,
            "folder_id": FOLDER,
            "object_id": "segment",
            "storage_path": "private/segment",
            "sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw),
            "committed_revision": 1,
        }
    ]
    sb.storage = SimpleNamespace(from_=lambda _: SimpleNamespace(download=lambda _: raw))
    return sb


def reference():
    return encode_reference(
        {
            "v": 1,
            "owner": OWNER,
            "folder": FOLDER,
            "session": SESSION,
            "event": "1" * 64,
            "start": 0,
            "length": 17,
            "after": None,
            "before": "2026-11-06T03:00:00+00:00",
            "timezone": "America/Sao_Paulo",
        }
    )


def test_evidence_reference_keeps_cutoff_for_neighbors_and_paired_results(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-only-reference-key")
    result = read_memory(archive(), OWNER, [FOLDER], reference(), before=3, after=3)
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["excerpt"] == "exec\nGOMEMLIMIT=3GiB"
    assert result["evidence"][0]["provenance"] == "command_only"
    assert result["time_scope"]["before_exclusive"] == "2026-11-06T03:00:00+00:00"


def test_references_are_reauthorized_and_tampering_is_rejected(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-only-reference-key")
    ref = reference()
    for user, allowed, token in [
        (OWNER, [SIBLING], ref),
        ("other", [FOLDER], ref),
        (OWNER, [FOLDER], ref[:-1] + "x"),
    ]:
        with pytest.raises(HTTPException):
            read_memory(archive(), user, allowed, token)


def test_lexical_index_contains_deep_spans_not_just_preview():
    full = "prefix " * 1000 + " rare_original_needle"
    chunks = list(
        chunks_for_event(
            {"event_id": "id", "displayable": True, "inherited": False, "_content": full}
        )
    )
    match = next(c for c in chunks if "rare_original_needle" in c["text"])
    assert match["char_start"] > 4096
    assert match["text"] == full[match["char_start"] : match["char_start"] + match["char_length"]]
    assert list(chunks_for_event({"displayable": True, "inherited": True, "_content": full})) == []


def test_api_and_native_tools_share_authorized_dispatch():
    from services.agent_memory_tools import execute_memory_tool

    with patch("services.agent_memory_tools.search_memory", return_value={"matches": []}) as search:
        execute_memory_tool(
            Database(),
            "search_agent_history",
            {"folder": "repo", "timezone": "America/Sao_Paulo"},
            OWNER,
            [FOLDER],
        )
        assert search.call_args.args[:3] == (search.call_args.args[0], OWNER, [FOLDER])
        assert search.call_args.kwargs["tz"] == "America/Sao_Paulo"
        assert search.call_args.kwargs["folder"] == "repo"
        search.reset_mock()
        result = json.loads(
            execute_memory_tool(
                Database(), "search_agent_history", {}, OWNER, [FOLDER], filename="one.md"
            )
        )
        assert result["code"] == "memory_requires_folder_scope"
        search.assert_not_called()


def test_weekly_root_activity_is_scoped_and_asof_omits_revised_summaries():
    sb = Database()
    sb.rows["agent_journal_search_entries"] = [
        {
            "user_id": OWNER,
            "folder_id": fid,
            "session_id": fid,
            "agent": "codex",
            "title": "Reported work",
            "summary": "Reported investigation, not deployed proof",
            "captured_at": "2026-11-06T20:00:00+00:00",
            "entry_id": fid,
        }
        for fid in [FOLDER, SIBLING]
    ]
    sb.rpc = lambda name, arguments: SimpleNamespace(
        execute=lambda: SimpleNamespace(
            data={"matches": [], "total_matches": 0, "index_pending_objects": 0, "has_more": False}
        )
    )
    result = search_memory(
        sb,
        OWNER,
        [ROOT, FOLDER, SIBLING],
        from_date="2026-11-02",
        through_date="2026-11-08",
        tz="America/Sao_Paulo",
    )
    assert len(result["activity"]["days"]) == 2
    assert all(r["source_kind"] == "journal_summary" for r in result["activity"]["days"])
    narrowed = search_memory(
        sb,
        OWNER,
        [ROOT, FOLDER, SIBLING],
        folder="repo",
        from_date="2026-11-02",
        through_date="2026-11-08",
    )
    assert len(narrowed["activity"]["days"]) == 1
    historical = search_memory(sb, OWNER, [ROOT, FOLDER, SIBLING], as_of="2026-11-06")
    assert historical["activity"] is None


def test_public_and_native_mcp_register_readonly_offloaded_memory_tools():
    import asyncio
    import inspect

    import mcp_server
    from services.ai.native_tools import native_mcp

    native = {tool.name: tool for tool in asyncio.run(native_mcp.list_tools())}
    for name in ["search_agent_history", "read_agent_evidence"]:
        tool = mcp_server.mcp._tool_manager.get_tool(name)
        assert inspect.iscoroutinefunction(tool.fn)
        assert tool.annotations.readOnlyHint is True
        assert native[name].annotations.readOnlyHint is True
        assert native[name].annotations.destructiveHint is False


def test_public_mcp_uses_key_authority_and_narrowing_not_model_owner_ids():
    import mcp_server

    token = mcp_server._current_user_id.set(OWNER)
    scope = mcp_server._current_scope_folder_id.set(ROOT)
    try:
        with (
            patch("mcp_server.get_supabase_thread_safe", return_value=Database()),
            patch("mcp_server._descendant_folder_ids", return_value=[ROOT, FOLDER, SIBLING]),
            patch(
                "services.agent_memory.search_memory", return_value={"status": "ok", "matches": []}
            ) as search,
        ):
            response = json.loads(
                mcp_server.search_agent_history(
                    query="heap", folder="repo", as_of="2026-11-05", timezone="America/Sao_Paulo"
                )
            )
            assert response["status"] == "ok"
            assert search.call_args.args[1:] == (OWNER, [ROOT, FOLDER, SIBLING])
            assert search.call_args.kwargs["folder"] == "repo"
            assert search.call_args.kwargs["as_of"] == "2026-11-05"
    finally:
        mcp_server._current_user_id.reset(token)
        mcp_server._current_scope_folder_id.reset(scope)


def test_native_chat_receives_browser_timezone_and_memory_tool_contract():
    from unittest.mock import MagicMock

    from services.ai.chat import prepare_turn

    sb = MagicMock()
    q = sb.table.return_value
    for method in ["select", "eq", "limit", "order"]:
        getattr(q, method).return_value = q
    q.execute.return_value.data = []
    sb.rpc.side_effect = lambda name, body: SimpleNamespace(
        execute=lambda: SimpleNamespace(data={"request": body["p_request"]})
    )
    with (
        patch("services.ai.chat.get_supabase_thread_safe", return_value=sb),
        patch("services.ai.chat.descendant_folder_ids", return_value=[FOLDER]),
        patch("services.ai.chat.execute_tool", return_value="No document evidence"),
        patch("services.ai.chat.save_trace"),
    ):
        result = prepare_turn(
            owner_id=OWNER,
            conversation_id="conversation",
            content="What did we work on this week?",
            turn_id="turn",
            model="sonnet",
            mode="deep",
            folder_id=FOLDER,
            filename=None,
            user_timezone="America/Sao_Paulo",
        )
    request = result["request"]
    assert request["metadata"]["user_timezone"] == "America/Sao_Paulo"
    assert "user timezone: America/Sao_Paulo" in request["system_prompt"]
    assert "Monday" in request["system_prompt"]
    assert {"search_agent_history", "read_agent_evidence"} <= set(request["tool_allowlist"])
    # Timezone is frozen in the prepared body, not added to user-intent equality;
    # resuming an existing turn from another computer doesn't reinterpret it.
    assert "timezone" not in request["metadata"]["intent"]


def test_fresh_mcp_transport_search_then_expand_preserves_time_scope(monkeypatch):
    from fastapi.testclient import TestClient

    import mcp_server

    sb = archive()
    full = "exec\nGOMEMLIMIT=3GiB"
    row = {
        "folder_id": FOLDER,
        "session_id": SESSION,
        "event_id": "1" * 64,
        "char_start": 0,
        "char_length": len(full),
        "native_session_id": "native",
        "agent": "codex",
        "event_at": "2026-11-05T23:00:00+00:00",
        "role": "tool",
        "event_type": "tool_call",
        "source_truncated": False,
    }
    sb.rpc = lambda name, body: SimpleNamespace(
        execute=lambda: SimpleNamespace(
            data={
                "matches": [row],
                "total_matches": 1,
                "index_pending_objects": 0,
                "has_more": False,
            }
        )
    )
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-only-reference-key")
    headers = {"Authorization": "Bearer fixture", "Accept": "application/json, text/event-stream"}

    def decoded(response):
        assert response.status_code == 200
        payload = next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
        message = json.loads(payload)
        return json.loads(message["result"]["content"][0]["text"])

    with (
        patch.object(mcp_server, "_verify_api_key", return_value=(OWNER, ROOT)),
        patch.object(mcp_server, "_descendant_folder_ids", return_value=[ROOT, FOLDER, SIBLING]),
        patch.object(mcp_server, "get_supabase_thread_safe", return_value=sb),
        patch.object(mcp_server, "get_supabase", return_value=sb),
        patch.object(mcp_server.mcp, "_session_manager", None),
        TestClient(mcp_server.build_app()) as client,
    ):
        initialized = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "memory-test", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200
        headers["Mcp-Session-Id"] = initialized.headers["Mcp-Session-Id"]
        client.post(
            "/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        result = decoded(
            client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "search_agent_history",
                        "arguments": {
                            "query": "Go memory budget",
                            "folder": "repo",
                            "as_of": "2026-11-05",
                            "timezone": "America/Sao_Paulo",
                        },
                    },
                },
            )
        )
        assert result["matches"][0]["excerpt"] == full
        result = decoded(
            client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {
                        "name": "read_agent_evidence",
                        "arguments": {
                            "reference": result["matches"][0]["reference"],
                            "after_records": 3,
                        },
                    },
                },
            )
        )
        assert len(result["evidence"]) == 1
        assert result["time_scope"]["before_exclusive"] == "2026-11-06T03:00:00+00:00"


def test_search_uses_indexed_prefix_without_storage_but_deep_hits_verify_original(monkeypatch):
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-only-reference-key")
    sb = archive()
    event = sb.rows["agent_evidence_events"][0]
    hit = {
        **event,
        "native_session_id": "native",
        "agent": "codex",
        "char_start": 0,
        "char_length": 20,
        "content_preview": "exec\nGOMEMLIMIT=3GiB",
    }
    hit["char_length"] = len(hit["content_preview"])
    sb.rpc = lambda *_: SimpleNamespace(
        execute=lambda: SimpleNamespace(data={"matches": [hit], "has_more": False})
    )
    with patch("services.agent_memory.original_text", side_effect=AssertionError("Storage read")):
        result = search_memory(sb, OWNER, [FOLDER], query="memory")
    assert result["matches"][0]["excerpt"] == "exec\nGOMEMLIMIT=3GiB"
    assert result["matches"][0]["provenance"] == "command_only"
    hit["content_preview"] = "exec"
    result = search_memory(sb, OWNER, [FOLDER], query="memory")
    assert result["matches"][0]["excerpt"] == "exec\nGOMEMLIMIT=3GiB"


def test_memory_backfill_publishes_complete_only_after_all_batches():
    from services.agent_memory_index import index_pending_memory

    sb = Database()
    sb.rows["agent_evidence_objects"] = [
        {
            "session_id": SESSION,
            "object_id": "segment",
            "kind": "segment",
            "committed_revision": 1,
            "indexed_parser_version": 1,
            "memory_index_version": 0,
            "first_record": 1,
            "descriptor": {"first_record": 1},
        }
    ]
    store = SimpleNamespace(sb=sb, _query=sb.table, download=lambda _: b"private fixture")
    event = {"event_id": "e", "displayable": True, "_content": "x" * 251000}
    with (
        patch("services.agent_memory_index.iter_segment", return_value=iter([event])),
        patch("services.agent_memory_index.rpc") as publish,
    ):
        index_pending_memory(store, {"id": SESSION})
    batches = [call.args[2] for call in publish.call_args_list]
    assert len(batches) == 2
    assert batches[0]["p_reset"] is True and batches[0]["p_complete"] is False
    assert len(batches[0]["p_chunks"]) == 250
    assert batches[1]["p_reset"] is False and batches[1]["p_complete"] is True
    assert len(batches[1]["p_chunks"]) == 1


@pytest.mark.parametrize("fraction", ["", ".3", ".33", ".333", ".3333", ".33333", ".333333"])
def test_postgres_timestamps_accept_variable_fraction_precision(fraction):
    from services.agent_memory import journal_activity

    sb = Database()
    sb.rows["agent_journal_search_entries"] = [
        {
            "user_id": OWNER,
            "folder_id": FOLDER,
            "session_id": "native",
            "agent": "codex",
            "title": "Reported work",
            "summary": "Reported work",
            "captured_at": "2026-11-06T02:10:12" + fraction + "+00:00",
            "entry_id": "entry",
        }
    ]
    result = journal_activity(sb, OWNER, [FOLDER], None, None, "America/Sao_Paulo")
    assert result["days"][0]["date"] == "2026-11-05"
    assert bounds(as_of="2026-11-06T02:10:12" + fraction + "+00:00")[1].startswith(
        "2026-11-06T02:10:12."
    )
