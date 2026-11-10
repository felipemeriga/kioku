"""Explicit runtime policy; no API fallback configuration exists."""

import os
from dataclasses import dataclass, field

NATIVE_VERSION = "2.1.318"


def validate_root_parallelism(value):
    if type(value) is not int or not 1 <= value <= 4:
        raise ValueError("TSUKAI_ROOT_PARALLELISM must be an integer from 1 to 4")
    return value


def configured_root_parallelism():
    value = os.getenv("TSUKAI_ROOT_PARALLELISM", "2")
    if value not in {"1", "2", "3", "4"}:
        raise ValueError("TSUKAI_ROOT_PARALLELISM must be an integer from 1 to 4")
    return int(value)


def heavy_maintenance(request):
    return (
        request.caller == "mihari"
        and request.profile == "completion"
        and request.operation in {"mihari.documentation", "mihari.reground"}
        and request.ai_depth == 0
    )


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("TSUKAI_DATABASE_URL", ""))
    service_token: str = field(default_factory=lambda: os.getenv("TSUKAI_SERVICE_TOKEN", ""))
    capability_key: str = field(default_factory=lambda: os.getenv("TSUKAI_CAPABILITY_KEY", ""))
    capability_issuer: str = field(
        default_factory=lambda: os.getenv("TSUKAI_CAPABILITY_ISSUER", "kioku-backend")
    )
    entitled_owners: frozenset[str] = field(
        default_factory=lambda: frozenset(
            filter(None, os.getenv("TSUKAI_ENTITLED_OWNER_IDS", "").split(","))
        )
    )
    workspace_dir: str = field(
        default_factory=lambda: os.getenv("TSUKAI_WORKSPACE_DIR", "/data/workspaces")
    )
    native_bin: str = field(default_factory=lambda: os.getenv("TSUKAI_NATIVE_BIN", "claude"))
    native_version: str = NATIVE_VERSION
    backend_url: str = field(default_factory=lambda: os.getenv("TSUKAI_BACKEND_URL", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("TSUKAI_REDIS_URL", ""))
    auth_probe: bool = field(
        default_factory=lambda: os.getenv("TSUKAI_AUTH_PROBE", "true").lower() == "true"
    )
    allowed_models: frozenset[str] = frozenset({"claude-sonnet-4-6", "claude-haiku-4-5-20251001"})
    first_event_seconds: float = 30
    idle_seconds: float = 120
    wall_seconds: float = 300
    maintenance_wall_seconds: float = 600
    kill_grace_seconds: float = 5
    heartbeat_seconds: float = 5
    drain_seconds: float = 120
    spool_bytes: int = 16 * 1024 * 1024
    subscriber_bytes: int = 1024 * 1024
    root_parallelism: int = field(default_factory=configured_root_parallelism)

    def __post_init__(self):
        validate_root_parallelism(self.root_parallelism)

    def validate(self):
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("production requires TSUKAI_DATABASE_URL PostgreSQL asyncpg")
        if len(self.service_token) < 32 or len(self.capability_key) < 32:
            raise ValueError("service and capability keys require at least32 characters")
        if self.service_token == self.capability_key:
            raise ValueError("transport and scope capability keys must differ")
