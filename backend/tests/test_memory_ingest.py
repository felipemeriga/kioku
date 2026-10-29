"""Raw memory ingress keeps evidence encrypted and acknowledges durable writes."""

import base64
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services.agent_memory import ingest


def event():
    content = "The user corrected the deployment command."
    return {
        "type": "memory_post",
        "protocol": 1,
        "event_id": "a" * 64,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "folder_id": str(uuid4()),
        "session_id": "session-1",
        "source": "claude_code",
        "source_schema_version": 1,
        "record_position": 10,
        "event_time": datetime.now(timezone.utc).isoformat(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "provenance": "user",
        "sensitivity": "normal",
        "content": content,
    }


def test_memory_post_rejects_content_hash_mismatch():
    data = event()
    data["content_hash"] = "b" * 64
    with pytest.raises(ValueError, match="content hash"):
        ingest.MemoryPost.model_validate(data)


@pytest.mark.parametrize("source", ["claude_memory", "codex_memory", "codex"])
def test_agent_sources_use_same_ingest_contract(source):
    data = event()
    data["source"] = source
    if source.endswith("memory"):
        data["provenance"] = "agent_memory"
    assert ingest.MemoryPost.model_validate(data).source == source


def test_envelope_encrypts_raw_and_binds_event_id(monkeypatch):
    key = bytes(range(32))

    class KMS:
        def generate_data_key(self, **kwargs):
            assert kwargs["EncryptionContext"]["event_id"] == "a" * 64
            return {"Plaintext": key, "CiphertextBlob": b"wrapped"}

    monkeypatch.setattr(ingest, "_kms", lambda: KMS())
    monkeypatch.setattr(ingest, "_kms_key_id", lambda: "test-key")
    sealed = ingest.encrypt_raw("secret evidence", "a" * 64)
    plaintext = AESGCM(key).decrypt(
        base64.b64decode(sealed["nonce"]),
        base64.b64decode(sealed["raw_ciphertext"]),
        bytes.fromhex("a" * 64),
    )
    assert plaintext == b"secret evidence"
    assert base64.b64decode(sealed["wrapped_dek"]) == b"wrapped"
    assert "secret evidence" not in str(sealed)


def test_accept_calls_atomic_rpc_and_returns_status(monkeypatch):
    calls = []

    class RPC:
        def execute(self):
            return type("Result", (), {"data": "stored"})()

    class DB:
        def rpc(self, name, params):
            calls.append((name, params))
            return RPC()

    monkeypatch.setattr(ingest, "get_supabase_thread_safe", lambda: DB())
    monkeypatch.setattr(
        ingest,
        "encrypt_raw",
        lambda content, event_id: {
            "raw_ciphertext": "encrypted",
            "wrapped_dek": "wrapped",
            "nonce": "nonce",
        },
    )
    data = ingest.MemoryPost.model_validate(event())
    assert ingest.accept_event(data, str(uuid4()), str(uuid4())) == "stored"
    assert calls[0][0] == "accept_memory_event"
    assert calls[0][1]["p_redacted_content"] == "[awaiting redaction]"
    assert data.content not in str(calls)
