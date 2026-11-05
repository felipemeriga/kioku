"""Version-one evidence transport. No transcript content enters model APIs."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

BUCKET = "agent-evidence"
MAX_OBJECT_BYTES = 64 * 1024 * 1024
MAX_BATCH_OBJECTS = 256
PARSER_VERSION = 1
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,179}$")


def attachment_content_type(original_name: str | None) -> str:
    """Viewer metadata hint only; authenticated bytes stay octet-stream/nosniff."""
    return mimetypes.guess_type(original_name or "")[0] or "application/octet-stream"


def safe_id(value: str) -> str:
    if not SAFE_ID.fullmatch(value) or ".." in value:
        raise ValueError("Invalid evidence identity")
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def event_id(folder: str, agent: str, native: str, stream: str, generation: int, record: int):
    return sha256(canonical([folder, agent, native, stream, generation, record]))


class ObjectDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal["segment", "attachment"]
    stream_id: str
    generation: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    byte_length: int = Field(ge=1, le=MAX_OBJECT_BYTES)
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, ge=1)
    first_record: int | None = Field(default=None, ge=1)
    last_record: int | None = Field(default=None, ge=1)
    record_count: int | None = Field(default=None, ge=1)
    original_name: str | None = Field(default=None, max_length=255)
    source_event_id: str | None = Field(default=None, max_length=180)
    source_schema: str | None = Field(default=None, max_length=80)

    @field_validator("id", "stream_id")
    @classmethod
    def valid_id(cls, value):
        return safe_id(value)

    @model_validator(mode="after")
    def valid_range(self):
        if self.kind == "segment":
            values = [self.source_start, self.source_end, self.first_record, self.last_record]
            if any(value is None for value in values):
                raise ValueError("Segments require source offsets and record range")
            if self.source_end - self.source_start != self.byte_length:
                raise ValueError("Segment byte range does not match length")
            if self.last_record < self.first_record:
                raise ValueError("Invalid source record range")
            count = self.last_record - self.first_record + 1
            if self.record_count is not None and count != self.record_count:
                raise ValueError("Invalid record count")
            self.record_count = count
        return self


class JournalLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    journal_entry_id: str = Field(min_length=1, max_length=512)
    journal_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_event_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    end_event_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class EvidenceGap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^[a-z_]{1,60}$")
    event_id: str | None = Field(default=None, max_length=180)
    name: str | None = Field(default=None, max_length=255)


class Lifecycle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["observed", "ended"] = "observed"
    ended_at: str | None = Field(default=None, max_length=40)

    @field_validator("ended_at")
    @classmethod
    def valid_instant(cls, value):
        if value is not None:
            from datetime import datetime

            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Lifecycle time must include timezone")
        return value


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: int = Field(default=1, alias="schema", ge=1, le=1)
    folder_id: str = Field(pattern=r"^[a-fA-F0-9-]{36}$")
    agent: Literal["claude_code", "codex"]
    native_session_id: str
    native_root_session_id: str | None = None
    native_parent_session_id: str | None = None
    producer_id: str
    batch_id: str
    base_revision: int = Field(ge=0)
    objects: list[ObjectDescriptor] = Field(max_length=MAX_BATCH_OBJECTS)
    journal_links: list[JournalLink] = Field(default_factory=list, max_length=256)
    gaps: list[EvidenceGap] = Field(default_factory=list, max_length=256)
    lifecycle: Lifecycle = Field(default_factory=Lifecycle)

    @field_validator(
        "native_session_id",
        "native_root_session_id",
        "native_parent_session_id",
        "producer_id",
        "batch_id",
    )
    @classmethod
    def valid_id(cls, value):
        return safe_id(value) if value is not None else None

    @model_validator(mode="after")
    def ancestry(self):
        if self.native_parent_session_id == self.native_session_id:
            raise ValueError("A session cannot parent itself")
        if self.native_parent_session_id and not self.native_root_session_id:
            raise ValueError("Child sessions require a root identity")
        if not self.native_parent_session_id:
            if self.native_root_session_id not in (None, self.native_session_id):
                raise ValueError("Root identity does not match root session")
            self.native_root_session_id = self.native_session_id
        if len({obj.id for obj in self.objects}) != len(self.objects):
            raise ValueError("Duplicate object descriptors")
        if len(canonical(self.model_dump(by_alias=True, exclude_none=True))) > 1024 * 1024:
            raise ValueError("Batch metadata exceeds limit")
        return self
