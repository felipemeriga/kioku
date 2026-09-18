"""The event dispatcher — routes gateway events to ledger logic.

Routing (SPEC "Events"):

- ``payment.settled``  → posting.build_settlement_entry → append to journal
- ``refund.completed`` → posting.build_refund_reversal_entry → append to journal
- ``payout.paid``      → payouts.mark_paid → append + mark batch paid

Idempotency: every event id is checked against the processed-event store before
any work. A redelivered event returns its original result and posts nothing new
(SPEC: "Consumers must be idempotent on event.id").
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import PostingError
from ..models.event import EventEnvelope
from ..payouts.builder import PayoutBuilder
from ..posting import build_refund_reversal_entry, build_settlement_entry
from ..repository import JournalStore, ProcessedEventStore
from . import parser
from .types import (
    CONSUMED,
    PAYMENT_SETTLED,
    PAYOUT_PAID,
    REFUND_COMPLETED,
)


@dataclass
class DispatchResult:
    """Outcome of dispatching a single event."""

    event_id: str
    event_type: str
    #: "posted" | "ignored" | "duplicate"
    status: str
    #: Journal id or batch id produced, if any.
    result_id: str | None = None


class EventDispatcher:
    """Idempotent router from events to posting / payout logic."""

    def __init__(
        self,
        journal: JournalStore,
        processed: ProcessedEventStore,
        payout_builder: PayoutBuilder,
    ) -> None:
        self._journal = journal
        self._processed = processed
        self._payouts = payout_builder

    def dispatch(self, envelope: EventEnvelope) -> DispatchResult:
        # -- idempotency guard: replay returns the original result ------------
        if self._processed.is_processed(envelope.id):
            prior = self._processed.get(envelope.id)
            return DispatchResult(
                event_id=envelope.id,
                event_type=envelope.type,
                status="duplicate",
                result_id=prior.result_id if prior else None,
            )

        # -- events the ledger does not act on: acknowledge + record ----------
        if envelope.type not in CONSUMED:
            self._processed.record(envelope.id, envelope.type, None)
            return DispatchResult(
                event_id=envelope.id, event_type=envelope.type, status="ignored"
            )

        result = self._handle(envelope)
        self._processed.record(envelope.id, envelope.type, result.result_id)
        return result

    # -- per-type handlers ----------------------------------------------------

    def _handle(self, envelope: EventEnvelope) -> DispatchResult:
        if envelope.type == PAYMENT_SETTLED:
            return self._handle_settled(envelope)
        if envelope.type == REFUND_COMPLETED:
            return self._handle_refund(envelope)
        if envelope.type == PAYOUT_PAID:
            return self._handle_payout_paid(envelope)
        # Unreachable: guarded by CONSUMED above.
        raise PostingError(f"no handler for consumed event type {envelope.type!r}")

    def _handle_settled(self, envelope: EventEnvelope) -> DispatchResult:
        data = parser.parse_settled(envelope)
        entry = build_settlement_entry(envelope.id, data)
        self._journal.append(entry)
        return DispatchResult(
            event_id=envelope.id, event_type=envelope.type, status="posted", result_id=entry.id
        )

    def _handle_refund(self, envelope: EventEnvelope) -> DispatchResult:
        data = parser.parse_refund(envelope)
        settlement = self._journal.settlement_for_charge(data.charge_id)
        if settlement is None:
            raise PostingError(
                "refund references a charge with no settlement entry",
                detail={"charge_id": data.charge_id, "refund_id": data.refund_id},
            )
        entry = build_refund_reversal_entry(envelope.id, data, settlement)
        self._journal.append(entry)
        return DispatchResult(
            event_id=envelope.id, event_type=envelope.type, status="posted", result_id=entry.id
        )

    def _handle_payout_paid(self, envelope: EventEnvelope) -> DispatchResult:
        data = parser.parse_payout_paid(envelope)
        _batch, entry = self._payouts.mark_paid(envelope.id, data)
        return DispatchResult(
            event_id=envelope.id, event_type=envelope.type, status="posted", result_id=entry.id
        )
