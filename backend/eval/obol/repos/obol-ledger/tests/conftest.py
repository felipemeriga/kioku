"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from obol_ledger.events import EventDispatcher
from obol_ledger.payouts import PayoutBuilder
from obol_ledger.payouts.gateway_client import GatewayClient, PayoutResponse
from obol_ledger.repository import JournalStore, PayoutBatchStore, ProcessedEventStore


class FakeGatewayClient(GatewayClient):
    """A GatewayClient that records requests instead of calling the network."""

    def __init__(self) -> None:
        super().__init__()
        self.requests = []

    async def create_payout(self, request):  # type: ignore[override]
        self.requests.append(request)
        return PayoutResponse(
            batch_id=request.batch_id, status="processing", processor_ref="po_ref_test"
        )


@pytest.fixture
def journal() -> JournalStore:
    return JournalStore()


@pytest.fixture
def batches() -> PayoutBatchStore:
    return PayoutBatchStore()


@pytest.fixture
def processed() -> ProcessedEventStore:
    return ProcessedEventStore()


@pytest.fixture
def fake_gateway() -> FakeGatewayClient:
    return FakeGatewayClient()


@pytest.fixture
def payout_builder(journal, batches, fake_gateway) -> PayoutBuilder:
    return PayoutBuilder(journal, batches, fake_gateway)


@pytest.fixture
def dispatcher(journal, processed, payout_builder) -> EventDispatcher:
    return EventDispatcher(journal, processed, payout_builder)
