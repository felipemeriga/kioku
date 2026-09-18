"""Runtime configuration, sourced from the environment.

Kept intentionally dependency-light (no pydantic-settings) so the ledger can
boot in minimal environments. Call :func:`get_settings` for a cached instance.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _get(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    """Immutable process configuration."""

    host: str = "0.0.0.0"
    port: int = 8081

    #: Base URL of the obol-gateway service.
    gateway_url: str = "http://localhost:8080"
    #: Optional bearer token for internal gateway calls.
    gateway_token: str | None = None
    #: Outbound HTTP timeout (seconds) for gateway calls.
    gateway_timeout: float = 10.0

    #: Default reporting currency used for sanity checks / examples.
    default_currency: str = "EUR"

    @property
    def payouts_url(self) -> str:
        """Fully-qualified gateway endpoint the payout builder posts to."""
        return f"{self.gateway_url.rstrip('/')}/v1/payouts"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process settings, read once from the environment."""
    return Settings(
        host=_get("OBOL_LEDGER_HOST", "0.0.0.0"),
        port=int(_get("OBOL_LEDGER_PORT", "8081")),
        gateway_url=_get("OBOL_GATEWAY_URL", "http://localhost:8080"),
        gateway_token=os.environ.get("OBOL_GATEWAY_TOKEN") or None,
        gateway_timeout=float(_get("OBOL_GATEWAY_TIMEOUT", "10.0")),
        default_currency=_get("OBOL_DEFAULT_CURRENCY", "EUR"),
    )
