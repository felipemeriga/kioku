"""Obol Ledger — the double-entry accounting core for the Obol platform.

This package consumes payment events emitted by ``obol-gateway`` and posts
immutable, balanced journal entries. It derives account balances from those
entries, produces statements, and builds seller payout batches (delegating the
actual money movement back to the gateway's ``POST /v1/payouts`` endpoint).

The single hard invariant enforced everywhere: **every journal entry balances**
— ``sum(debits) == sum(credits)`` in a single currency.
"""

__version__ = "0.1.0"
