"""Strict, bounded request contracts. Never serialize invalid credential input."""

import re
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Guide(StrictModel):
    markdown: str = Field(max_length=65536)
    expected_revision: int = Field(ge=0)

    @field_validator("markdown")
    @classmethod
    def guide_bytes(cls, value):
        if len(value.encode()) > 65536:
            raise ValueError("Guide is too large")
        return value


class Environment(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    sensitivity: Literal["normal", "production"] = "normal"

    @field_validator("slug")
    @classmethod
    def reserved(cls, value):
        if value == "shared":
            raise ValueError("Shared describes resource availability, not an environment")
        return value


class Resource(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    type: Literal["database", "observability", "cloud", "other"]
    aliases: list[str] = Field(default_factory=list, max_length=20)
    shared: bool = False
    account: str = Field(default="", max_length=120)
    region: str = Field(default="", max_length=120)

    @field_validator("aliases")
    @classmethod
    def aliases_valid(cls, value):
        if any(not item.strip() or len(item) > 120 for item in value):
            raise ValueError("Invalid alias")
        return list(dict.fromkeys(value))


def env_name(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
        raise ValueError("Invalid environment variable name")
    if value.startswith(("LD_", "DYLD_")) or value in {
        "NODE_OPTIONS",
        "BASH_ENV",
        "ENV",
        "PYTHONSTARTUP",
        "PYTHONPATH",
        "PATH",
        "HOME",
        "USERPROFILE",
        "COMSPEC",
        "SystemRoot",
        "PATHEXT",
        "IFS",
        "CDPATH",
        "ZDOTDIR",
        "SHELLOPTS",
        "BASHOPTS",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_CONFIG_FILE",
        "AWS_SHARED_CREDENTIALS_FILE",
        "AWS_WEB_IDENTITY_TOKEN_FILE",
        "AWS_ROLE_ARN",
        "AWS_ROLE_SESSION_NAME",
        "AWS_EC2_METADATA_DISABLED",
        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN",
        "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
    }:
        raise ValueError("Runtime control variables are not supported")
    return value


class Binding(StrictModel):
    resource_id: UUID
    environment_id: UUID | None = None
    consumer: str = Field(min_length=1, max_length=120)
    field_mapping: dict[str, str] = Field(min_length=1, max_length=32)
    clear_env: list[str] = Field(default_factory=list, max_length=32)
    enabled: bool = True

    @field_validator("field_mapping")
    @classmethod
    def mapping_valid(cls, value):
        for key, field in value.items():
            env_name(key)
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", field):
                raise ValueError("Invalid credential field")
        return value

    @field_validator("clear_env")
    @classmethod
    def clear_valid(cls, value):
        # Clearing control selectors is allowed; injecting them is not.
        if any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", k)
            or k in {"PATH", "HOME", "USERPROFILE", "COMSPEC", "SystemRoot", "PATHEXT"}
            for k in value
        ):
            raise ValueError("Invalid cleared variable name")
        return list(dict.fromkeys(value))


class BindingUpdate(Binding):
    expected_revision: int = Field(ge=1)


class Credential(StrictModel):
    # Whitespace is significant in credential values.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    expected_revision: int = Field(ge=1)
    idempotency_key: UUID
    values: dict[str, str] = Field(min_length=1, max_length=32, repr=False)
    credential_expires_at: datetime | None = None

    @field_validator("values")
    @classmethod
    def values_valid(cls, value):
        total = 0
        for field, secret in value.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", field):
                raise ValueError("Invalid credential field")
            size = len(secret.encode())
            if not secret or "\x00" in secret or size > 65536:
                raise ValueError("Invalid credential value")
            total += size
        if total > 262144:
            raise ValueError("Credential payload is too large")
        return value

    @field_validator("credential_expires_at")
    @classmethod
    def expiry_valid(cls, value):
        if value is not None and (value.tzinfo is None or value <= datetime.now(timezone.utc)):
            raise ValueError("Credential expiry must be a future timestamp with timezone")
        return value


class Grant(StrictModel):
    device_id: UUID
    binding_id: UUID
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def expiry(cls, v):
        return Credential.expiry_valid(v)


class Enrollment(StrictModel):
    root_id: UUID
    label: str = Field(min_length=1, max_length=120)


class Approval(StrictModel):
    binding_ids: list[UUID] = Field(default_factory=list, max_length=100)


class Poll(StrictModel):
    request_id: UUID
    device_code: str = Field(min_length=32, max_length=200, repr=False)


class BindingRef(StrictModel):
    binding_id: UUID
    revision: int = Field(ge=1)


class Resolve(StrictModel):
    root_id: UUID
    invocation_id: UUID
    bindings: list[BindingRef] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def distinct(self):
        if len({b.binding_id for b in self.bindings}) != len(self.bindings):
            raise ValueError("Duplicate binding")
        return self
