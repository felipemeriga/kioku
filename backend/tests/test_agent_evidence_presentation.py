"""Sanitized native records; source fidelity and partial-document safeguards."""

import json

import pytest

from services.agent_evidence_presentation import fragment_presentation, present


def codex(kind, **payload):
    return {"type": "response_item", "payload": {"type": kind, **payload}}


def test_native_message_boundaries_and_code():
    record = codex(
        "message",
        role="assistant",
        content=[
            {"type": "output_text", "text": "# Result"},
            {"type": "code", "language": "python", "text": "print('sanitized')"},
            {"type": "output_text", "text": "Done."},
        ],
    )
    result = present(record, "codex")
    assert [b["kind"] for b in result["blocks"]] == ["markdown", "code", "markdown"]
    assert result["blocks"][1]["language"] == "python"
    assert not result["viewer_truncated"]


def test_command_native_arguments_metadata_preserved():
    args = {"cmd": "printf 'sanitized'", "cwd": "/tmp/example"}
    result = present(
        codex("function_call", name="exec_command", call_id="call-1", arguments=json.dumps(args)),
        "codex",
    )
    assert result["tool"] == {
        "name": "exec_command",
        "call_id": "call-1",
        "command_text": args["cmd"],
        "cwd": args["cwd"],
    }
    assert json.loads(result["blocks"][0]["text"]) == args


def test_nested_output_envelope_unwraps_only_known_fields():
    envelope = {
        "output": json.dumps(
            {
                "stdout": "sanitized output\n",
                "stderr": "warning\n",
                "metadata": {"exit_code": 0, "duration_seconds": 1.2},
            }
        ),
        "wall_time_seconds": 2.1,
    }
    record = codex("function_call_output", call_id="c", output=json.dumps(envelope))
    before = json.dumps(record, sort_keys=True)
    result = present(record, "codex")
    assert [b["text"] for b in result["blocks"]] == ["sanitized output\n", "warning\n"]
    assert result["tool"]["exit_code"] == 0 and result["tool"]["duration_seconds"] == 1.2
    assert result["tool"]["orchestration_seconds"] == 2.1
    assert json.dumps(record, sort_keys=True) == before


def test_native_command_header_extracts_timing_without_leaking_wrapper():
    value = (
        "Chunk ID: sanitized\nWall time: 0.25 seconds\n"
        "Process exited with code 0\nFinal output:\nhello\n"
    )
    result = present(codex("function_call_output", output=value), "codex")
    assert result["blocks"] == [{"kind": "terminal", "text": "hello\n", "viewer_truncated": False}]
    assert result["tool"]["exit_code"] == 0 and result["tool"]["orchestration_seconds"] == 0.25
    prose = "The result says Wall time: 2 seconds\nOutput:\nkeep all this"
    assert (
        present(codex("function_call_output", output=prose), "codex")["blocks"][0]["text"] == prose
    )


def test_claude_tool_result_and_native_command_metadata():
    call = {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "id": "c",
                    "name": "Bash",
                    "input": {"command": "echo sanitized", "cwd": "/tmp"},
                }
            ]
        },
    }
    assert present(call, "claude_code")["tool"]["command_text"] == "echo sanitized"
    result = {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "c", "content": "preview"}]},
        "toolUseResult": {
            "stdout": "full native body",
            "stderr": "",
            "exitCode": 0,
            "durationMs": 125,
        },
    }
    value = present(result, "claude_code")
    assert value["blocks"][0]["text"] == "full native body"
    assert value["tool"]["duration_seconds"] == 0.125 and value["tool"]["exit_code"] == 0


def test_native_item_result_metadata_and_output():
    record = {
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "item": {
                "id": "c",
                "type": "CommandExecution",
                "aggregated_output": "hello",
                "exit_code": 0,
                "duration_ms": 250,
                "command": ["echo", "hello world"],
                "cwd": "/tmp",
            },
        },
    }
    result = present(record, "codex", {"event_type": "tool_result"})
    assert result["blocks"][0]["text"] == "hello"
    assert result["tool"]["command_text"] == "echo 'hello world'"
    assert result["tool"]["duration_seconds"] == 0.25


def test_complete_json_only_when_complete_and_preserve_source_warning():
    value = json.dumps({"safe": "🐈" * 50})
    record = codex("function_call_output", output=value)
    full = present(record, "codex", limit_bytes=4096)
    assert full["blocks"][0]["kind"] == "json" and json.loads(full["blocks"][0]["text"])
    clipped = present(record, "codex", limit_bytes=20)
    assert clipped["blocks"][0]["kind"] == "text" and clipped["viewer_truncated"]
    assert not clipped["source_truncated"]
    warning = present(
        codex("function_call_output", output="Warning: truncated output\nbody"), "codex"
    )
    assert warning["source_truncated"] and not warning["viewer_truncated"]
    assert fragment_presentation('{"partial":', False) == {
        "version": 1,
        "blocks": [{"kind": "text", "text": '{"partial":', "viewer_truncated": True}],
        "viewer_truncated": True,
        "source_truncated": False,
    }


@pytest.mark.parametrize("value", ["{incomplete", "NaN", "<script>alert('sanitized')</script>", ""])
def test_unrecognized_tool_text_is_not_rewritten(value):
    result = present(codex("function_call_output", output=value), "codex")
    assert result["blocks"] == [{"kind": "terminal", "text": value, "viewer_truncated": False}]


def test_codex_native_exec_source_is_code_without_unwrapping_or_execution():
    code = "text(await tools.exec_command({cmd: 'echo sanitized'}));"
    value = present(codex("custom_tool_call", name="exec", input=code), "codex")
    assert value["blocks"] == [
        {"kind": "code", "language": "javascript", "text": code, "viewer_truncated": False}
    ]
    unknown = present(codex("custom_tool_call", name="unrecognized", input=code), "codex")
    assert unknown["blocks"][0]["kind"] == "text"


def test_item_completed_message_uses_full_native_content_not_preview():
    record = {
        "type": "event_msg",
        "payload": {
            "type": "item_completed",
            "item": {
                "type": "AgentMessage",
                "content": [{"type": "text", "text": "native complete"}],
            },
        },
    }
    value = present(record, "codex", {"event_type": "message", "content_preview": "native"})
    assert value["blocks"][0]["text"] == "native complete"


@pytest.mark.parametrize("oversized", [False, True])
def test_window_reuses_one_segment_download_for_multiple_presentations(monkeypatch, oversized):
    from types import SimpleNamespace

    from services.agent_evidence import EvidenceStore
    from services.agent_evidence_parser import parse_segment

    records = [
        codex("message", role="user", content=[{"type": "input_text", "text": "first"}]),
        codex("message", role="assistant", content=[{"type": "output_text", "text": "second"}]),
    ]
    raw = b"".join((json.dumps(r) + "\n").encode() for r in records)
    session = {
        "id": "s",
        "agent": "codex",
        "native_session_id": "native",
        "folder_id": "folder",
        "manifest_revision": 1,
        "indexed_revision": 1,
        "index_generation": 1,
        "index_status": "ready",
    }
    events, _ = parse_segment(
        raw,
        {
            "stream_id": "native",
            "generation": 1,
            "first_record": 1,
            "last_record": 2,
            "record_count": 2,
        },
        session,
    )
    for i, event in enumerate(events):
        event.update(object_id="obj", session_id="s", position=str(i + 1))
    if oversized:
        events[0]["call_id"] = "x" * 600000
    obj = {"object_id": "obj", "session_id": "s", "kind": "segment", "committed_revision": 1}

    if oversized:
        events[0]["call_id"] = "x" * 600000

    class Query:
        def __init__(self, rows):
            self.rows = list(rows)

        @property
        def not_(self):
            return self

        def is_(self, *_):
            return self

        def eq(self, key, value):
            self.rows = [r for r in self.rows if r.get(key) == value]
            return self

        def in_(self, key, values):
            self.rows = [r for r in self.rows if r.get(key) in values]
            return self

        def lt(self, key, value):
            self.rows = [r for r in self.rows if r.get(key) < value]
            return self

        def gt(self, key, value):
            self.rows = [r for r in self.rows if r.get(key) > value]
            return self

        def order(self, *args, **kwargs):
            return self

        def limit(self, count):
            self.rows = self.rows[:count]
            return self

        def execute(self):
            return SimpleNamespace(data=self.rows)

    store = EvidenceStore(None, "owner", "folder")
    monkeypatch.setattr(store, "session", lambda *args: session)
    monkeypatch.setattr(store, "metadata", lambda *args: {"children": []})
    monkeypatch.setattr(
        store, "_query", lambda table: Query(events if table == "agent_evidence_events" else [obj])
    )
    downloads = []
    monkeypatch.setattr(store, "download", lambda *args: downloads.append("obj") or raw)
    value = store.window("s")
    assert len(downloads) == 1
    assert len(value["events"]) == 2  # Even a first oversize event cannot hide the page.
    if oversized:
        assert value["events"][0]["viewer_truncated"]
    assert [e["presentation"]["blocks"][0]["text"] for e in value["events"]] == ["first", "second"]


def test_expanded_content_fragment_is_text_and_complete_json_keeps_structure(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes.agent_evidence as module

    full = '{"sanitized": "complete document"}'
    presentation = {
        "version": 1,
        "blocks": [{"kind": "json", "text": full}],
        "viewer_truncated": False,
        "source_truncated": False,
    }

    class Store:
        def event(self, *args):
            return {}

        def event_content_view(self, *args):
            return full, presentation

    monkeypatch.setattr(module, "_read_store", lambda *args: Store())
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[module.get_current_user] = lambda: "owner"
    client = TestClient(app)
    base = "/api/folders/folder/agent-sessions/s/events/e/content"
    complete = client.get(base).json()
    assert complete["presentation"]["blocks"][0]["kind"] == "json" and not complete["has_more"]
    part = client.get(base + "?limit_bytes=8").json()
    assert part["has_more"] and part["next_offset"] == 8
    assert part["presentation"]["blocks"] == [
        {"kind": "text", "text": full[:8], "viewer_truncated": True}
    ]
    assert part["presentation"]["viewer_truncated"]


@pytest.mark.parametrize(
    "document",
    [
        {"output": "retained", "other": 3},
        {"content": "retained", "other": 3},
        {"stdout": "retained", "exit_code": 0, "business_field": "keep"},
        {"output": "retained", "metadata": {"unknown_business_key": 3}},
        {"output": "retained"},
    ],
)
def test_unknown_business_json_keeps_every_field(document):
    result = present(codex("function_call_output", output=json.dumps(document)), "codex")
    assert result["blocks"][0]["kind"] == "json"
    assert json.loads(result["blocks"][0]["text"]) == document


def test_outer_orchestration_timing_not_overwritten_by_inner_tool_runtime():
    inner = {"output": "actual command body", "wall_time_seconds": 0.25, "exit_code": 0}
    outer = {
        "output": json.dumps(inner),
        "chunk_id": "safe",
        "wall_time_seconds": 2.1,
        "exit_code": 0,
        "original_token_count": 10,
    }
    result = present(codex("function_call_output", output=json.dumps(outer)), "codex")
    assert result["tool"]["orchestration_seconds"] == 2.1
    assert result["tool"]["duration_seconds"] == 0.25
    assert result["blocks"][0]["text"] == "actual command body"


def test_unknown_native_tool_payload_fields_are_preserved_as_json():
    record = codex("function_call_output", output="native text", future_field={"preserved": 3})
    result = present(record, "codex")
    assert result["blocks"][0]["text"] == "native text"
    assert json.loads(result["blocks"][1]["text"]) == {"future_field": {"preserved": 3}}


def test_twenty_thousand_empty_blocks_are_bounded_and_expanded_text_remains_complete(monkeypatch):
    from services.agent_evidence import EvidenceStore
    from services.agent_evidence_models import canonical

    record = codex(
        "message",
        role="assistant",
        content=[{"type": "output_text", "text": ""} for _ in range(20000)],
    )
    before = canonical(record)
    value = present(record, "codex")
    assert len(value["blocks"]) <= 128 and value["viewer_truncated"]
    assert len(canonical(value)) <= 65536
    store = EvidenceStore(None, "owner", "folder")
    monkeypatch.setattr(store, "session", lambda *args: {"agent": "codex"})
    monkeypatch.setattr(store, "event_raw", lambda *args: before)
    content, presentation = store.event_content_view("s", {})
    assert (
        content == "\n" * 19999
    )  # Presentation preview bounds never remove expanded native content.
    assert presentation["blocks"][0]["text"] == content
    assert canonical(record) == before


def test_huge_call_identifier_and_serialized_control_character_overhead_are_bounded():
    from services.agent_evidence_models import canonical

    huge = "c" * 600000
    record = codex(
        "function_call",
        name="shell",
        call_id=huge,
        arguments=json.dumps({"cmd": "\u0001" * 6000, "cwd": "\u0002" * 6000}),
        status="\u0003" * 6000,
    )
    value = present(record, "codex")
    assert len(canonical(value)) <= 65536 and value["viewer_truncated"]
    assert "tool" not in value or len(value["tool"]["call_id"].encode()) <= 512
    assert record["payload"]["call_id"] == huge


@pytest.mark.parametrize(
    "envelope",
    [
        {"output": "partial", "exit_code": 0, "truncated": True},
        {"output": "partial", "metadata": {"exit_code": 0, "truncated": True}},
    ],
)
def test_recognized_native_truncation_flag_survives_unwrapping(envelope):
    result = present(codex("function_call_output", output=json.dumps(envelope)), "codex")
    assert result["source_truncated"] and result["blocks"][0]["text"] == "partial"
    assert not result["viewer_truncated"]


def test_unknown_business_truncation_field_is_not_inferred():
    document = {"output": "business data", "truncated": True, "unknown_business": 3}
    result = present(codex("function_call_output", output=json.dumps(document)), "codex")
    assert not result["source_truncated"]
    assert json.loads(result["blocks"][0]["text"]) == document


def test_oversized_native_call_identifiers_remain_distinct_after_metadata_bounding():
    one = "same-prefix" * 1000 + "one"
    two = "same-prefix" * 1000 + "two"
    first = present(codex("function_call_output", call_id=one, output="body"), "codex")
    second = present(codex("function_call_output", call_id=two, output="body"), "codex")
    assert first["tool"]["call_id"] != second["tool"]["call_id"]
    assert len(first["tool"]["call_id"].encode()) <= 512 and first["viewer_truncated"]


def test_complete_first_block_remains_complete_when_later_native_fields_are_clipped():
    first = 'fn sanitized() { println!("complete"); }\n' + "x" * 4010
    record = codex("function_call_output", output=first, extra_native_metadata="m" * 10000)
    result = present(record, "codex", limit_bytes=8192)
    assert result["viewer_truncated"]
    assert result["blocks"][0]["text"] == first
    assert result["blocks"][0]["viewer_truncated"] is False
    assert result["blocks"][1]["viewer_truncated"] is True
    assert result["blocks"][1]["kind"] == "text"  # Clipped metadata is not complete JSON.


def test_preview_budget_allows_eight_kibibytes_of_native_presentation():
    # Direct adapter budget used by window: all4056 native bytes plus4KiBmetadata fit.
    native = "x" * 4056
    metadata = "m" * 4000
    record = codex("function_call_output", output=native, additional_metadata=metadata)
    result = present(record, "codex", limit_bytes=8192)
    assert not result["viewer_truncated"]
    assert result["blocks"][0]["text"] == native and not result["blocks"][0]["viewer_truncated"]
    assert json.loads(result["blocks"][1]["text"]) == {"additional_metadata": metadata}
