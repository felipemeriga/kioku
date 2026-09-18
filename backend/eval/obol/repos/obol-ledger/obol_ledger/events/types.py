"""Canonical event-type string constants (SPEC "Events")."""

from __future__ import annotations

PAYMENT_AUTHORIZED = "payment.authorized"
PAYMENT_SETTLED = "payment.settled"
REFUND_COMPLETED = "refund.completed"
PAYOUT_SCHEDULED = "payout.scheduled"
PAYOUT_PAID = "payout.paid"

#: Event types the ledger actively consumes (others are acknowledged + ignored).
CONSUMED = frozenset({PAYMENT_SETTLED, REFUND_COMPLETED, PAYOUT_PAID})
