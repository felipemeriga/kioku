"""Per-model-call usage and list-price accounting for chat and Mihari."""

import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterator

from db.client import get_supabase_thread_safe

logger = logging.getLogger(__name__)

# USD per million tokens. Keep the model IDs and rates used at call time in
# each ledger row; changing this table must not reprice historical calls.
PRICES = {
    "claude-haiku-4-5-20251001": (Decimal("1"), Decimal("5")),
    "claude-sonnet-4-6": (Decimal("3"), Decimal("15")),
}
PRICE_VERSION = "anthropic-list-2026-11-03"


@dataclass(frozen=True)
class UsageAttribution:
    user_id: str
    source: str
    operation: str
    folder_id: str | None = None
    conversation_id: str | None = None
    response_id: str | None = None
    round_number: int | None = None


class UsageCollector:
    """Shared across chat tool workers; flushed with the answer's rounds."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self._lock = threading.Lock()

    def add(self, row: dict) -> None:
        with self._lock:
            self.rows.append(row)


_active_usage: ContextVar[tuple[UsageAttribution, UsageCollector] | None] = ContextVar(
    "active_usage", default=None
)


@contextmanager
def collect_usage(attribution: UsageAttribution, collector: UsageCollector) -> Iterator[None]:
    token = _active_usage.set((attribution, collector))
    try:
        yield
    finally:
        _active_usage.reset(token)


def current_usage() -> tuple[UsageAttribution, UsageCollector] | None:
    return _active_usage.get()


def usage_row(message, attribution: UsageAttribution) -> dict:
    """Preserve Anthropic's four billing counters and the served model ID."""
    usage = message.usage
    cache_creation = getattr(usage, "cache_creation", None)
    cache_write_total = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_write_1h = getattr(cache_creation, "ephemeral_1h_input_tokens", 0) or 0
    cache_write_5m = getattr(cache_creation, "ephemeral_5m_input_tokens", 0) or 0
    if not cache_creation:
        cache_write_5m = cache_write_total
    model = str(message.model)
    prices = PRICES.get(model)
    cost = None
    if prices:
        input_price, output_price = prices
        cost = (
            Decimal(usage.input_tokens) * input_price
            + Decimal(usage.output_tokens) * output_price
            + Decimal(cache_write_5m) * input_price * Decimal("1.25")
            + Decimal(cache_write_1h) * input_price * Decimal("2")
            + Decimal(getattr(usage, "cache_read_input_tokens", 0) or 0)
            * input_price
            * Decimal("0.1")
        ) / Decimal(1_000_000)
    return {
        "user_id": attribution.user_id,
        "source": attribution.source,
        "operation": attribution.operation,
        "folder_id": attribution.folder_id,
        "conversation_id": attribution.conversation_id,
        "response_id": attribution.response_id,
        "round_number": attribution.round_number,
        "provider_message_id": getattr(message, "id", None),
        "model": model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_write_5m_tokens": cache_write_5m,
        "cache_write_1h_tokens": cache_write_1h,
        "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "list_cost_usd": str(cost) if cost is not None else None,
        "price_version": PRICE_VERSION if prices else None,
    }


def save_usage(rows: list[dict]) -> None:
    if not rows:
        return
    for attempt in range(3):
        try:
            get_supabase_thread_safe().table("llm_usage_events").upsert(
                rows, on_conflict="provider_message_id"
            ).execute()
            return
        except Exception:  # noqa: BLE001
            if attempt == 2:
                logger.error("failed to save model usage for %d call(s)", len(rows), exc_info=True)
            else:
                time.sleep(0.2 * (attempt + 1))
