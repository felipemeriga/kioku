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
    assert metadata["content_type"] == "image/png"
    response = client.get(base + "/attachments/a?download=true")
    assert (
        response.content == b"0123456789"
        and "attachment;" in response.headers["content-disposition"]
    )


@pytest.mark.parametrize("source", [b'{"type":"user","message":{"content":"original"}}\n', b""])
def test_upload_route_passes_supported_file_to_real_storage_sdk(monkeypatch, source):
    """Exercise real SDK multipart encoding; BufferedRandom is not supported."""
    import io

    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from storage3 import SyncStorageClient

    import routes.agent_evidence as module

    calls = []

    def respond(request):
        calls.append(request.read())
        return httpx.Response(200, json={"Key": "agent-evidence/session/segment.jsonl"})

    transport = httpx.MockTransport(respond)
    with httpx.Client(transport=transport) as client:
        storage = SyncStorageClient("https://storage.example/storage/v1/", {}, http_client=client)

        class Store:
            def upload(self, batch_id, object_id, file, content_hash, length):
                assert isinstance(file, io.FileIO)
                assert length == len(source) and content_hash == sha256(source)
                storage.from_("agent-evidence").upload(
                    "session/segment.jsonl",
                    file,
                    {"content-type": "application/octet-stream", "upsert": "false"},
                )
                return {"status": "stored"}

        monkeypatch.setattr(module, "_key_store", lambda *args: Store())
        app = FastAPI()
        app.include_router(module.router)
        response = TestClient(app).put("/api/agent-evidence/batches/b/objects/o", content=source)
        assert response.status_code == 200, response.text
    assert len(calls) == 1 and source in calls[0]


@pytest.mark.parametrize(
    "name,expected",
    [
        ("tool-output.txt", "text/plain"),
        ("payload.json", "application/json"),
        ("opaque.kiokuraw", "application/octet-stream"),
        (None, "application/octet-stream"),
    ],
)
def test_attachment_metadata_mime_hint(name, expected):
    from services.agent_evidence_models import attachment_content_type

    assert attachment_content_type(name) == expected


def test_empty_attachment_descriptor_accepted_but_empty_segment_rejected():
    attachment = dict(
        id="empty",
        kind="attachment",
        stream_id="native",
        generation=1,
        sha256=sha256(b""),
        byte_length=0,
        original_name="empty.txt",
    )
    assert ObjectDescriptor(**attachment).byte_length == 0
    with pytest.raises(ValidationError):
        ObjectDescriptor(
            **{
                **attachment,
                "kind": "segment",
                "source_start": 0,
                "source_end": 1,
                "first_record": 1,
                "last_record": 1,
                "record_count": 1,
            }
        )


class EvidenceLookupDB:
    """Apply real owner/folder filters in fallback tests, without external services."""

    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        from types import SimpleNamespace

        class Query:
            def __init__(self, rows):
                self.rows = list(rows)

            def select(self, *_):
                return self

            def eq(self, key, value):
                self.rows = [r for r in self.rows if r.get(key) == value]
                return self

            def is_(self, key, _):
                self.rows = [r for r in self.rows if r.get(key) is None]
                return self

            def limit(self, count):
                self.rows = self.rows[:count]
                return self

            def execute(self):
                return SimpleNamespace(data=self.rows)

        return Query(self.tables.get(name, []))


def fallback_store(sessions, links=None, events=None):
    return EvidenceStore(
        EvidenceLookupDB(
            {
                "agent_evidence_sessions": sessions,
                "agent_evidence_journal_links": links or [],
                "agent_evidence_events": events or [],
            }
        ),
        "owner",
        FOLDER,
    )


def evidence_session(**overrides):
    return {
        "id": "session-id",
        "user_id": "owner",
        "folder_id": FOLDER,
        "agent": "codex",
        "native_session_id": "native",
        "parent_session_id": None,
        **overrides,
    }


def test_missing_alias_returns_only_approximate_session_no_event_range():
    assert fallback_store([evidence_session()]).resolve_entry("codex:native:turn") == {
        "status": "approximate",
        "session_id": "session-id",
    }
    assert (
        fallback_store([evidence_session(native_session_id="native:with:colon")]).resolve_entry(
            "codex:native:with:colon:turn"
        )["status"]
        == "approximate"
    )


@pytest.mark.parametrize(
    "entry",
    [
        "",
        "native",
        "codex:native",
        "codex::turn",
        "codex:native:",
        "unknown:native:turn",
        "codex:../native:turn",
    ],
)
def test_malformed_alias_does_not_guess_session(entry):
    assert fallback_store([evidence_session()]).resolve_entry(entry) == {"status": "absent"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"user_id": "other"},
        {"folder_id": "other"},
        {"agent": "claude_code"},
        {"parent_session_id": "parent"},
    ],
)
def test_approximate_link_respects_owner_folder_agent_root(overrides):
    assert fallback_store([evidence_session(**overrides)]).resolve_entry("codex:native:turn") == {
        "status": "absent",
    }


def test_ambiguous_fallback_and_deleted_session():
    assert fallback_store([evidence_session(), evidence_session(id="duplicate")]).resolve_entry(
        "codex:native:turn"
    ) == {"status": "absent"}
    assert fallback_store([evidence_session(deleted_at="now")]).resolve_entry(
        "codex:native:turn"
    ) == {
        "status": "deleted",
    }


@pytest.mark.parametrize("indexed,expected", [(False, "pending"), (True, "available")])
def test_exact_alias_still_wins_over_approximate(indexed, expected):
    link = {
        "user_id": "owner",
        "folder_id": FOLDER,
        "journal_entry_id": "codex:native:turn",
        "session_id": "session-id",
        "start_event_id": "anchor",
        "end_event_id": None,
    }
    events = (
        [
            {
                "user_id": "owner",
                "folder_id": FOLDER,
                "session_id": "session-id",
                "event_id": "anchor",
            }
        ]
        if indexed
        else []
    )
    result = fallback_store([evidence_session()], links=[link], events=events).resolve_entry(
        "codex:native:turn"
    )
    assert result["status"] == expected and result["start_event_id"] == "anchor"


@pytest.mark.parametrize(
    "zone,first,last,expected_start,expected_end",
    [
        (
            "America/Sao_Paulo",
            "2026-11-05T00:30:00Z",
            "2026-11-05T00:45:00+00:00",
            "2026-11-04",
            "2026-11-04",
        ),
        (
            "Pacific/Kiritimati",
            "2026-11-04T12:30:00Z",
            "2026-11-04T13:00:00Z",
            "2026-11-05",
            "2026-11-05",
        ),
        (
            "Pacific/Kiritimati",
            "2026-11-06T12:30:00Z",
            "2026-11-06T13:00:00Z",
            "2026-11-07",
            "2026-11-07",
        ),
    ],
)
def test_session_days_defaults_use_requested_timezone_and_include_future_archive(
    monkeypatch, zone, first, last, expected_start, expected_end
):
    from datetime import datetime, timezone

    import services.agent_evidence as module

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(module, "datetime", FrozenDateTime)
    store = EvidenceStore(None, "owner", FOLDER)
    monkeypatch.setattr(
        store,
        "session",
        lambda *args: {"folder_id": FOLDER, "first_event_at": first, "last_event_at": last},
    )
    calls = []
    monkeypatch.setattr(module, "rpc", lambda *args: calls.append(args[2]) or [])
    store.days("session", zone)
    assert calls[0]["p_from"] == expected_start and calls[0]["p_to"] == expected_end


def test_session_days_explicit_bounds_remain_unchanged(monkeypatch):
    from datetime import date

    import services.agent_evidence as module

    store = EvidenceStore(None, "owner", FOLDER)
    monkeypatch.setattr(
        store,
        "session",
        lambda *args: {
            "folder_id": FOLDER,
            "first_event_at": "2026-11-05T00:30:00Z",
            "last_event_at": "2026-11-05T00:45:00Z",
        },
    )
    calls = []
    monkeypatch.setattr(module, "rpc", lambda *args: calls.append(args[2]) or [])
    store.days("session", "America/Sao_Paulo", date(2026, 11, 1), date(2026, 11, 3))
    assert calls[0]["p_from"] == "2026-11-01" and calls[0]["p_to"] == "2026-11-03"


@pytest.mark.parametrize("fraction", ["1", "51", "1234", "12345"])
def test_python310_supabase_fractional_timestamp_defaults(monkeypatch, fraction):
    from datetime import datetime, timezone

    import services.agent_evidence as module
    from services.agent_evidence_models import Lifecycle
    from services.agent_evidence_parser import instant

    stamp = f"2026-11-05T02:31:57.{fraction}+00:00"

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 5, 1, 0, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(module, "datetime", FrozenDateTime)
    store = EvidenceStore(None, "owner", FOLDER)
    monkeypatch.setattr(
        store,
        "session",
        lambda *args: {"folder_id": FOLDER, "first_event_at": stamp, "last_event_at": stamp},
    )
    calls = []
    monkeypatch.setattr(module, "rpc", lambda *args: calls.append(args[2]) or [])
    store.days("session", "America/Sao_Paulo")
    assert calls[0]["p_from"] == "2026-11-04" and calls[0]["p_to"] == "2026-11-04"
    assert Lifecycle(status="ended", ended_at=stamp).ended_at == stamp
    assert instant(stamp) is not None


@pytest.mark.parametrize("raw", [b"", b'{"code":"SELECT * FROM users;"}\n', b"\x00\xff" * 1024])
def test_lossless_storage_encoding_preserves_original_identity(raw):
    import gzip

    from services.agent_evidence import decode_stored_object

    obj = {"byte_length": len(raw), "sha256": sha256(raw)}
    assert decode_stored_object(raw, obj) == raw
    assert decode_stored_object(gzip.compress(raw, mtime=0), obj) == raw
    assert decode_stored_object(gzip.compress(raw + b"extra"), obj) is None
    assert decode_stored_object(gzip.compress(raw)[:-3], obj) is None
    assert decode_stored_object(b"not the original", obj) is None
    # An actual gzip attachment is an original, not another encoding layer.
    attachment = gzip.compress(raw)
    assert (
        decode_stored_object(
            attachment, {"byte_length": len(attachment), "sha256": sha256(attachment)}
        )
        == attachment
    )


@pytest.mark.parametrize("at_limit", [False, True])
def test_upload_storage_roundtrip_and_duplicate_verify_original_bytes(monkeypatch, at_limit):
    import gzip
    import tempfile
    from types import SimpleNamespace

    from storage3.exceptions import StorageApiError

    import services.agent_evidence as module

    raw = b'{"output":"original transcript SQL and code"}\n'
    obj = {"sha256": sha256(raw), "byte_length": len(raw), "kind": "segment"}
    stored = {}
    if at_limit:
        monkeypatch.setattr(module, "MAX_OBJECT_BYTES", len(raw))

    class Bucket:
        def upload(self, path, file, options):
            assert file.readable()
            encoded = file.read()
            assert (encoded if at_limit else gzip.decompress(encoded)) == raw
            if path in stored:
                raise StorageApiError("exists", "Duplicate", 409)
            stored[path] = encoded

        def download(self, path):
            return stored[path]

    bucket = Bucket()
    store = EvidenceStore(SimpleNamespace(storage=SimpleNamespace(from_=lambda _: bucket)), "u")
    monkeypatch.setattr(
        store, "batch", lambda _: {"session_id": "s", "request_json": {"objects": [{"id": "o"}]}}
    )
    monkeypatch.setattr(store, "object", lambda *a, **kw: obj)
    monkeypatch.setattr(store, "session", lambda _: {"id": "s"})
    monkeypatch.setattr(store, "prefix", lambda _: "private/session")
    monkeypatch.setattr(module, "rpc", lambda sb, name, args: {"nonce": "n", "uploaded": False})
    for _ in range(2):
        with tempfile.TemporaryFile(buffering=0) as file:
            file.write(raw)
            file.seek(0)
            assert store.upload("b", "o", file, sha256(raw), len(raw))["status"] == "stored"
    assert store.download({**obj, "storage_path": next(iter(stored))}) == raw
