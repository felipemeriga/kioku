"""Payout batch builder (SPEC cross-repo relationship #4).

Flow:

1. Derive the seller's ``seller_payable`` balance from the journal.
2. Build a :class:`PayoutBatch` for that (positive) balance.
3. Call gateway ``POST /v1/payouts`` to actually move the money → PROCESSING.
4. Later, on ``payout.paid``, :meth:`mark_paid` posts the balancing entry that
   debits ``seller_payable`` and credits ``processor_clearing``, driving the
   seller's payable balance back down by the paid amount.
"""

from __future__ import annotations

from ..accounts.chart import (
    PROCESSOR_CLEARING,
    seller_payable_account,
)
from ..balances.derive import balance_for_account
from ..config import get_settings
from ..errors import InsufficientBalanceError, PayoutBatchNotFoundError, PostingError
from ..models.event import PayoutPaidData
from ..models.journal_entry import JournalEntry
from ..models.journal_line import JournalLine
from ..models.payout_batch import PayoutBatch, PayoutBatchStatus
from ..money import Money
from ..repository import JournalStore, PayoutBatchStore
from .gateway_client import GatewayClient, PayoutRequest


class PayoutBuilder:
    """Builds, submits, and settles payout batches for sellers."""

    def __init__(
        self,
        journal: JournalStore,
        batches: PayoutBatchStore,
        gateway: GatewayClient | None = None,
    ) -> None:
        self._journal = journal
        self._batches = batches
        self._gateway = gateway or GatewayClient()
        self._default_currency = get_settings().default_currency

    # -- balance helper -------------------------------------------------------

    def payable_balance(self, seller_id: str) -> Money:
        """The seller's current ``seller_payable`` balance (amount owed)."""
        account = seller_payable_account(seller_id)
        pairs = self._journal.lines_for_account(account)
        derived = balance_for_account(account, pairs, default_currency=self._default_currency)
        return derived.balance

    # -- build + submit -------------------------------------------------------

    async def build_and_submit(
        self, seller_id: str, amount: Money | None = None
    ) -> PayoutBatch:
        """Build a batch for ``seller_id`` and submit it to the gateway.

        With no ``amount``, the full available payable balance is paid out. The
        requested amount may not exceed the payable balance.
        """
        available = self.payable_balance(seller_id)
        if available.is_zero or available.is_negative:
            raise InsufficientBalanceError(
                "seller has no positive payable balance",
                detail={"seller_id": seller_id, "available_minor": available.amount_minor},
            )

        payout_amount = amount or available
        if payout_amount.currency != available.currency:
            raise PostingError(
                "payout currency does not match seller payable currency",
                detail={"payout": payout_amount.currency, "payable": available.currency},
            )
        if payout_amount > available:
            raise InsufficientBalanceError(
                "requested payout exceeds available payable balance",
                detail={
                    "seller_id": seller_id,
                    "requested_minor": payout_amount.amount_minor,
                    "available_minor": available.amount_minor,
                },
            )

        batch = PayoutBatch(seller_id=seller_id, amount=payout_amount)
        self._batches.save(batch)

        response = await self._gateway.create_payout(
            PayoutRequest(batch_id=batch.id, seller_id=seller_id, amount=payout_amount)
        )
        batch = batch.mark_processing(processor_ref=response.processor_ref)
        return self._batches.save(batch)

    # -- settle on payout.paid ------------------------------------------------

    def mark_paid(self, event_id: str, data: PayoutPaidData) -> tuple[PayoutBatch, JournalEntry]:
        """Handle ``payout.paid``: post the debit entry and mark the batch paid.

        Posts::

            DEBIT  seller_payable:{seller}   amount
            CREDIT processor_clearing        amount

        which reduces what Obol owes the seller by the paid amount.
        """
        batch = self._batches.get(data.batch_id)
        if batch is None:
            raise PayoutBatchNotFoundError(
                "payout.paid references unknown batch",
                detail={"batch_id": data.batch_id},
            )

        seller_account = seller_payable_account(data.seller_id)
        entry = JournalEntry(
            event_id=event_id,
            kind="payout",
            currency=data.amount.currency,
            lines=[
                JournalLine.debit(seller_account, data.amount, memo="payout: seller balance paid"),
                JournalLine.credit(
                    PROCESSOR_CLEARING, data.amount, memo="payout: funds sent to seller bank"
                ),
            ],
            reference={"batch_id": data.batch_id, "seller_id": data.seller_id},
        ).assert_balanced()

        self._journal.append(entry)
        batch = batch.mark_paid(
            processor_ref=data.processor_ref, settlement_journal_id=entry.id
        )
        self._batches.save(batch)
        return batch, entry

    def get_batch(self, batch_id: str) -> PayoutBatch:
        batch = self._batches.get(batch_id)
        if batch is None:
            raise PayoutBatchNotFoundError(
                "payout batch not found", detail={"batch_id": batch_id}
            )
        return batch
