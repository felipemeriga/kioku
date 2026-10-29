"""Validate and durably store Manabi evidence without publishing it as memory."""

import base64
import hashlib
import os
from datetime import datetime
from typing import Literal
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field, model_validator

from db.client import get_supabase_thread_safe
from services.crypto import _kms, _kms_key_id

HASH = r"^[a-f0-9]{64}$"


class MemoryPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["memory_post"]
    protocol: Literal[1]
    event_id: str = Field(pattern=HASH)
    content_hash: str = Field(pattern=HASH)
    folder_id: UUID
    session_id: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    source_schema_version: int = Field(ge=1, le=100)
    record_position: int = Field(ge=0)
    event_time: datetime | None = None
    observed_at: datetime
    provenance: Literal[
        "user", "assistant", "tool_result", "external_text", "agent_memory", "unknown"
    ]
    sensitivity: Literal["normal", "redacted"]
    content: str = Field(min_length=1, max_length=60_000)

    @model_validator(mode="after")
    def validate_content(self):
        if hashlib.sha256(self.content.encode()).hexdigest() != self.content_hash:
            raise ValueError("content hash mismatch")
        if self.observed_at.tzinfo is None or (
            self.event_time is not None and self.event_time.tzinfo is None
        ):
            raise ValueError("memory timestamps must include timezone")
        return self


def encrypt_raw(content: str, event_id: str) -> dict[str, str]:
    """Use a per-event AES key; KMS only wraps its 32-byte key."""
    key = _kms().generate_data_key(
        KeyId=_kms_key_id(),
        KeySpec="AES_256",
        EncryptionContext={"app": "kioku", "event_id": event_id},
    )
    nonce = os.urandom(12)
    ciphertext = AESGCM(key["Plaintext"]).encrypt(nonce, content.encode(), bytes.fromhex(event_id))
    return {
        "raw_ciphertext": base64.b64encode(ciphertext).decode(),
        "wrapped_dek": base64.b64encode(key["CiphertextBlob"]).decode(),
        "nonce": base64.b64encode(nonce).decode(),
    }


def accept_event(event: MemoryPost, user_id: str, machine_id: str) -> str:
    """RPC commits raw evidence and HOLDING together before caller sends ack."""
    sealed = encrypt_raw(event.content, event.event_id)
    result = (
        get_supabase_thread_safe()
        .rpc(
            "accept_memory_event",
            {
                "p_user_id": user_id,
                "p_machine_id": machine_id,
                "p_event_id": event.event_id,
                "p_folder_id": str(event.folder_id),
                "p_source": event.source,
                "p_source_schema_version": event.source_schema_version,
                "p_session_id": event.session_id,
                "p_record_position": event.record_position,
                "p_content_hash": event.content_hash,
                **{f"p_{key}": value for key, value in sealed.items()},
                # The first slice never exposes source content to a model.
                # A dedicated redaction stage will populate this derived field.
                "p_redacted_content": "[awaiting redaction]",
                "p_event_time": event.event_time.isoformat() if event.event_time else None,
                "p_observed_at": event.observed_at.isoformat(),
                "p_provenance": event.provenance,
                "p_sensitivity": event.sensitivity,
            },
        )
        .execute()
    )
    if result.data not in ("stored", "duplicate"):
        raise RuntimeError("Unexpected memory acceptance result")
    return result.data
