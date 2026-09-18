"""Application state container + FastAPI dependency wiring.

Bundles the in-memory stores, account registry, payout builder, and event
dispatcher into a single :class:`LedgerState`, constructed once at startup and
exposed to routers via FastAPI dependencies.
"""

from __future__ import annotations

from fastapi import Request

from .accounts import AccountRegistry
from .config import get_settings
from .events import EventDispatcher
from .payouts import GatewayClient, PayoutBuilder
from .repository import JournalStore, PayoutBatchStore, ProcessedEventStore


class LedgerState:
    """Holds every long-lived collaborator the ledger needs."""

    def __init__(self, gateway_client: GatewayClient | None = None) -> None:
        settings = get_settings()
        self.settings = settings
        self.accounts = AccountRegistry(default_currency=settings.default_currency)
        self.journal = JournalStore()
        self.batches = PayoutBatchStore()
        self.processed = ProcessedEventStore()
        self.gateway = gateway_client or GatewayClient(settings=settings)
        self.payout_builder = PayoutBuilder(self.journal, self.batches, self.gateway)
        self.dispatcher = EventDispatcher(self.journal, self.processed, self.payout_builder)


def get_state(request: Request) -> LedgerState:
    """FastAPI dependency: fetch the app-wide :class:`LedgerState`."""
    return request.app.state.ledger
