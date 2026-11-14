"""Bounded metadata and delivery contracts. Credential values use the V1 safe body."""

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from services.root_access.models import Binding, Credential, StrictModel, env_name

CredentialKind = Literal["uri", "api_key", "ssh", "fields", "aws"]
Capability = Literal["env", "argv", "raw_secret_argv", "file", "ssh"]


def field_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
        raise ValueError("Invalid field name")
    return value


class CredentialInstance(StrictModel):
    resource_id: UUID
    environment_id: UUID | None = None
    label: str = Field(default="", max_length=120)
    kind: CredentialKind = "fields"
    fields: list[str] = Field(min_length=1, max_length=32)
    enabled: bool = True
    region: str = Field(default="", max_length=120)

    @field_validator("fields")
    @classmethod
    def fields_valid(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate credential field")
        return [field_name(v) for v in value]

    @model_validator(mode="after")
    def schema_valid(self):
        fields = set(self.fields)
        if self.kind == "ssh" and (
            not {"private_key"} <= fields or not fields <= {"private_key", "passphrase"}
        ):
            raise ValueError("Invalid SSH fields")
        if self.kind == "aws" and (
            not {"access_key_id", "secret_access_key"} <= fields
            or not fields <= {"access_key_id", "secret_access_key", "session_token"}
        ):
            raise ValueError("Invalid AWS fields")
        return self


class CredentialInstanceUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    resource_id: UUID | None = None
    environment_id: UUID | None = None
    label: str | None = Field(default=None, max_length=120)
    kind: CredentialKind | None = None
    fields: list[str] | None = Field(default=None, min_length=1, max_length=32)
    enabled: bool | None = None
    region: str | None = Field(default=None, max_length=120)


class EnvDelivery(StrictModel):
    kind: Literal["env"]
    field_mapping: dict[str, str] = Field(min_length=1, max_length=32)
    clear_env: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("field_mapping")
    @classmethod
    def mapping(cls, value):
        return Binding.mapping_valid(value)

    @field_validator("clear_env")
    @classmethod
    def clearing(cls, value):
        return Binding.clear_valid(value)


class LiteralArgument(StrictModel):
    kind: Literal["literal"]
    value: str = Field(max_length=4096)

    @field_validator("value")
    @classmethod
    def no_null(cls, value):
        if "\x00" in value:
            raise ValueError("Invalid argument")
        return value


class FieldArgument(StrictModel):
    kind: Literal["field"]
    field: str

    @field_validator("field")
    @classmethod
    def valid(cls, value):
        return field_name(value)


class ArgvDelivery(StrictModel):
    kind: Literal["argv"]
    arguments: list[Annotated[LiteralArgument | FieldArgument, Field(discriminator="kind")]] = (
        Field(min_length=1, max_length=64)
    )
    allow_raw_secret_argv: bool = False

    @model_validator(mode="after")
    def acknowledged(self):
        if any(a.kind == "field" for a in self.arguments) and not self.allow_raw_secret_argv:
            raise ValueError("Raw credential arguments require explicit acknowledgment")
        return self


class FilePatch(StrictModel):
    path: list[str] = Field(min_length=1, max_length=16)
    field: str

    @field_validator("field")
    @classmethod
    def valid(cls, value):
        return field_name(value)

    @field_validator("path")
    @classmethod
    def path_valid(cls, value):
        for segment in value:
            if (
                not segment
                or len(segment) > 128
                or segment in {".", "..", "__proto__", "prototype", "constructor"}
                or any(c in segment for c in ("\x00", "\\", "/"))
            ):
                raise ValueError("Invalid configuration path")
        return value


class FileDestination(StrictModel):
    kind: Literal["env", "arg"]
    name: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def valid(self):
        if self.kind == "env":
            if self.name != "AWS_SHARED_CREDENTIALS_FILE":
                env_name(self.name)
        elif not re.fullmatch(r"--?[A-Za-z][A-Za-z0-9_-]*", self.name):
            raise ValueError("Invalid configuration flag")
        return self


class FileDelivery(StrictModel):
    kind: Literal["file"]
    format: Literal["json", "yaml", "toml"]
    source_template: str = Field(default="", max_length=65536)
    patches: list[FilePatch] = Field(min_length=1, max_length=32)
    destination: FileDestination

    @model_validator(mode="after")
    def paths_valid(self):
        paths = [tuple(p.path) for p in self.patches]
        if len(set(paths)) != len(paths) or any(
            a != b and a == b[: len(a)] for a in paths for b in paths
        ):
            raise ValueError("Conflicting configuration paths")
        if "\x00" in self.source_template or len(self.source_template.encode()) > 65536:
            raise ValueError("Invalid configuration template")
        return self


class SSHDelivery(StrictModel):
    kind: Literal["ssh"]
    host: str = Field(min_length=1, max_length=253)
    user: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
    port: int = Field(default=22, ge=1, le=65535)
    host_key: str = Field(min_length=10, max_length=16384)
    private_key_field: Literal["private_key"] = "private_key"
    passphrase_field: Literal["passphrase"] | None = None

    @field_validator("host")
    @classmethod
    def host_valid(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", value):
            raise ValueError("Invalid SSH host")
        return value

    @field_validator("host_key")
    @classmethod
    def key_valid(cls, value):
        from cryptography.hazmat.primitives.serialization import load_ssh_public_key

        try:
            parts = value.split()
            if len(parts) != 2:
                raise ValueError("Invalid pinned host key")
            load_ssh_public_key(value.encode())
        except Exception:
            raise ValueError("Invalid pinned host key") from None
        return value


Delivery = Annotated[
    EnvDelivery | ArgvDelivery | FileDelivery | SSHDelivery, Field(discriminator="kind")
]


class Usage(StrictModel):
    credential_id: UUID
    name: str = Field(min_length=1, max_length=120)
    consumer: str = Field(min_length=1, max_length=240)
    delivery: Delivery
    enabled: bool = True


class UsageUpdate(Usage):
    expected_revision: int = Field(ge=1)


class UsageGrant(StrictModel):
    device_id: UUID
    usage_id: UUID
    allowed_fields: list[str] = Field(min_length=1, max_length=32)
    capabilities: list[Capability] = Field(min_length=1, max_length=5)
    expires_at: datetime | None = None

    @field_validator("allowed_fields")
    @classmethod
    def valid(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Duplicate field")
        return [field_name(v) for v in value]

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, value):
        from datetime import datetime

        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return Credential.expiry_valid(value)


class RequestedUsage(StrictModel):
    usage_id: UUID
    revision: int = Field(ge=1)
    credential_revision: int = Field(ge=1)


class ResolveV2(StrictModel):
    root_id: UUID
    invocation_id: UUID
    usages: list[RequestedUsage] = Field(min_length=1, max_length=8)
    allow_raw_secret_argv: bool = False

    @field_validator("usages")
    @classmethod
    def unique(cls, value):
        if len({x.usage_id for x in value}) != len(value):
            raise ValueError("Duplicate usage")
        return value


def usage_fields(delivery: dict) -> set[str]:
    match delivery["kind"]:
        case "env":
            return set(delivery["field_mapping"].values())
        case "argv":
            return {a["field"] for a in delivery["arguments"] if a["kind"] == "field"}
        case "file":
            return {p["field"] for p in delivery["patches"]}
        case "ssh":
            return {delivery["private_key_field"]} | (
                {delivery["passphrase_field"]} if delivery.get("passphrase_field") else set()
            )
    raise ValueError("Unknown delivery")


def usage_capabilities(delivery: dict) -> set[str]:
    return {delivery["kind"]} | (
        {"raw_secret_argv"} if delivery["kind"] == "argv" and usage_fields(delivery) else set()
    )
