"""Original source fidelity, bounded projections, validation and scoped paging."""

import json

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from services.agent_evidence import EvidenceStore
from services.agent_evidence_models import BatchRequest, ObjectDescriptor, event_id, sha256
from services.agent_evidence_parser import parse_segment

FOLDER = "22222222-2222-4222-8222-222222222222"
SESSION = {
    "folder_id": FOLDER,
    "agent": "codex",
    "native_session_id": "session",
    "parent_session_id": None,
}


def parse(records, session=None, state=None):
    raw = b"".join((json.dumps(r, ensure_ascii=False) + "\n").encode() for r in records)
    descriptor = {
        "stream_id": "native",
        "generation": 1,
        "first_record": 1,
        "record_count": len(records),
        "last_record": len(records),
    }
    events, state = parse_segment(raw, descriptor, session or SESSION, state)
    return raw, events, state


def test_utf8_offsets_and_stable_raw_identity():
    raw, events, _ = parse(
        [
            {
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": "Olá 🐈"},
            },
            {"type": "new_unknown", "payload": {"secret": "preserved"}},
        ]
    )
    assert len(events) == 2
    assert events[0]["content_preview"] == "Olá 🐈"
    for i, e in enumerate(events):
        assert e["event_id"] == event_id(FOLDER, "codex", "session", "native", 1, i + 1)
        original = raw[e["byte_offset"] : e["byte_offset"] + e["byte_length"]]
        assert json.loads(original)["type"] in ("response_item", "new_unknown")
    assert not events[1]["displayable"]


def test_lf_only_invalid_record_is_retained():
    raw = b'{"type":"unknown","x":"bad\rraw"}\n'
    events, _ = parse_segment(
        raw,
        {"stream_id": "s", "generation": 1, "first_record": 1, "last_record": 1, "record_count": 1},
        SESSION,
    )
    assert len(events) == 1 and events[0]["event_type"] == "parse_error"
    assert events[0]["byte_length"] == len(raw)


def test_child_inherited_context_and_native_turn():
    child = {**SESSION, "parent_session_id": "parent"}
    _, events, state = parse(
        [
            {"type": "session_meta", "payload": {"id": "parent"}},
            {
                "type": "response_item",
                "payload": {"type": "message", "role": "user", "content": "inherited"},
            },
            {"type": "session_meta", "payload": {"id": "session"}},
            {"type": "turn_context", "payload": {"turn_id": "turn-7"}},
            {
                "type": "response_item",
                "payload": {"type": "message", "role": "assistant", "content": "own"},
            },
        ],
        child,
    )
    assert events[1]["inherited"]
    assert not events[4]["inherited"] and events[4]["turn_id"] == "turn-7"
    assert state["own_context"]


def test_previews_bounded_original_not_truncated():
    raw, events, _ = parse(
        [
            {
                "type": "response_item",
                "payload": {"type": "function_call_output", "call_id": "c", "output": "🐈" * 10000},
            }
        ]
    )
    assert len(events[0]["content_preview"].encode()) <= 4096
    assert len(raw) > 30000
    assert not events[0]["source_truncated"]


def test_claude_richer_result_and_turn_carry():
    session = {**SESSION, "agent": "claude_code"}
    _, events, state = parse(
        [
            {"type": "user", "uuid": "turn-a", "message": {"content": "hello"}},
            {
                "type": "user",
                "message": {
                    "content": [{"type": "tool_result", "tool_use_id": "call", "content": "short"}]
                },
                "toolUseResult": {"stdout": "longer original tool result"},
            },
        ],
        session,
    )
    assert events[1]["content_preview"] == "longer original tool result"
    assert events[1]["turn_id"] == "turn-a"
    assert events[1]["call_id"] == "call"


@pytest.mark.parametrize("native", ["../escape", "a/b", "a\\b", "a..b", ""])
def test_unsafe_native_ids_rejected(native):
    with pytest.raises(ValidationError):
        BatchRequest(
            folder_id=FOLDER,
            agent="codex",
            native_session_id=native,
            producer_id="pc",
            batch_id="b",
            base_revision=0,
            objects=[],
        )


def test_segment_range_and_checksum_descriptor_validation():
    descriptor = dict(
        id="obj",
        kind="segment",
        stream_id="s",
        generation=1,
        sha256=sha256(b"{}\n"),
        byte_length=3,
        source_start=0,
        source_end=3,
        first_record=1,
        last_record=1,
        record_count=1,
    )
    assert ObjectDescriptor(**descriptor).record_count == 1
    with pytest.raises(ValidationError):
        ObjectDescriptor(**{**descriptor, "source_end": 4})


def test_cursor_binds_owner_mode_and_live_index_generation():
    store = EvidenceStore(None, "owner", FOLDER)
    s = {"id": "session", "folder_id": FOLDER, "manifest_revision": 2, "index_generation": 4}
    cursor = store._cursor(s, "native/1/2")
    assert store._position(s, cursor) == "native/1/2"
    for changed, mode in [({**s, "index_generation": 5}, "events"), (s, "raw")]:
        with pytest.raises(HTTPException) as exc:
            store._position(changed, cursor, mode)
        assert exc.value.status_code == 409
    with pytest.raises(HTTPException):
        EvidenceStore(None, "other", FOLDER)._position(s, cursor)


def test_conflict_receipt_is_http409_not_string_status(monkeypatch):
    import services.agent_evidence as module

    store = EvidenceStore(None, "owner", FOLDER)
    monkeypatch.setattr(store, "batch", lambda _: {})
    monkeypatch.setattr(
        module,
        "rpc",
        lambda *args: {"status": "conflict", "code": "revision_conflict", "current_revision": 7},
    )
    with pytest.raises(HTTPException) as exc:
        store.commit("batch")
    assert exc.value.status_code == 409
    assert exc.value.detail["current_revision"] == 7


def test_authenticated_raw_range_and_attachment_metadata(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import routes.agent_evidence as module

    class Store:
        def event(self, *args):
            return {}

        def event_raw(self, *args):
            return b"0123456789"

        def object(self, *args):
            return {
                "object_id": "a",
                "kind": "attachment",
                "descriptor": {"original_name": "test.png"},
                "byte_length": 10,
                "sha256": "f" * 64,
                "uploaded_at": "now",
            }

        def download(self, *args):
            return b"0123456789"

    monkeypatch.setattr(module, "_read_store", lambda *args: Store())
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[module.get_current_user] = lambda: "owner"
    client = TestClient(app)
    base = f"/api/folders/{FOLDER}/agent-sessions/s"
    response = client.get(base + "/events/e/raw", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206 and response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert client.get(base + "/events/e/raw", headers={"Range": "bytes=99-100"}).status_code == 416
    metadata = client.get(base + "/attachments/a").json()
    assert metadata["original_name"] == "test.png" and metadata["available"]
    response = client.get(base + "/attachments/a?download=true")
    assert (
        response.content == b"0123456789"
        and "attachment;" in response.headers["content-disposition"]
    )
