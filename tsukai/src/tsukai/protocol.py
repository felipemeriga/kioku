"""Canonical v1 HTTP models; generated JSON schemas live under protocol/."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TERMINAL = frozenset({"completed", "failed", "cancelled", "uncertain"})


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobRequest(StrictModel):
    schema_version: Literal[1] = 1
    idempotency_key: str = Field(min_length=1, max_length=200)
    owner_id: str = Field(min_length=1, max_length=128)
    caller: Literal["backend", "mcp", "mihari"]
    operation: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_.-]*$")
    profile: Literal["completion", "chat", "metadata_child"] = "completion"
    prompt: str = Field(min_length=1, max_length=1_000_000)
    system_prompt: str = Field(default="", max_length=100_000)
    model: str = Field(default="claude-sonnet-4-6", pattern=r"^[a-zA-Z0-9_.-]+$", max_length=100)
    max_tokens: int = Field(default=4096, ge=1, le=64000)
    max_turns: int = Field(default=8, ge=1, le=30)
    thinking_tokens: int = Field(default=0, ge=0, le=32000)
    response_schema: dict[str, Any] | None = None
    conversation_id: str | None = Field(default=None, max_length=128)
    folder_ids: list[str] = Field(default_factory=list, max_length=100)
    tool_allowlist: list[str] = Field(default_factory=list, max_length=30)
    tool_capability_ref: str | None = Field(default=None, max_length=512)
    parent_job_id: str | None = None
    root_job_id: str | None = None
    ai_depth: Literal[0, 1] = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent_profile(self):
        if (self.profile == "chat") != bool(self.conversation_id):
            raise ValueError("only chat requires conversation_id")
        if self.profile == "chat" and self.caller != "backend":
            raise ValueError("only UI backend can resume chat")
        if self.profile == "metadata_child":
            if (
                self.operation != "text_to_sql"
                or self.ai_depth != 1
                or not self.parent_job_id
                or not self.root_job_id
                or self.tool_allowlist
                or self.tool_capability_ref
            ):
                raise ValueError("metadata child requires bounded depth1 text_to_sql without tools")
        elif self.ai_depth or self.parent_job_id or self.root_job_id:
            raise ValueError("root profile cannot claim parent or depth")
        if self.profile == "completion" and (self.tool_allowlist or self.tool_capability_ref):
            raise ValueError("completion tools must be disabled; supply evidence explicitly")
        if self.thinking_tokens and self.thinking_tokens >= self.max_tokens:
            raise ValueError("thinking budget must be below output budget")
        if self.tool_allowlist and not self.tool_capability_ref:
            raise ValueError("tools require backend capability reference")
        if self.response_schema:
            from jsonschema import Draft202012Validator

            Draft202012Validator.check_schema(self.response_schema)
        return self


class Capability(StrictModel):
    iss: str
    aud: Literal["tsukai"]
    sub: Literal["backend", "mcp", "mihari"]
    owner_id: str
    folder_ids: list[str]
    operations: list[str]
    profiles: list[Literal["completion", "chat", "metadata_child"]]
    tool_allowlist: list[str] = Field(default_factory=list)
    iat: int
    exp: int
    jti: str
    ai_depth: Literal[0, 1] = 0
    parent_job_id: str | None = None
    root_job_id: str | None = None


class Event(StrictModel):
    schema_version: Literal[1] = 1
    job_id: str
    attempt_id: str | None
    seq: int
    type: str
    data: dict[str, Any]
    created_at: str


class Ack(StrictModel):
    consumer: str = Field(min_length=1, max_length=100)
    reference: str = Field(min_length=1, max_length=512)


class CompletionEnvelope(StrictModel):
    schema_version: Literal[1] = 1
    outcome: Literal["completed", "needs_input", "failed"]
    data: Any = None
    missing_inputs: list[dict[str, str]] = Field(default_factory=list)
    failure: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def outcome_union(self):
        if self.outcome == "completed":
            if self.data is None or self.missing_inputs or self.failure:
                raise ValueError("completed requires data and no missing inputs/failure")
        elif self.outcome == "needs_input":
            if self.data is not None or self.failure or not self.missing_inputs:
                raise ValueError("needs_input requires missing_inputs only")
            if any(not x.get("field") or not x.get("reason") for x in self.missing_inputs):
                raise ValueError("missing inputs require field and reason")
        elif self.data is not None or not self.failure:
            raise ValueError("failed requires failure and null data")
        return self
