"""Prefixed snake-case ID generation.

Per SPEC "Conventions": IDs are prefixed snake ids — ``chg_``, ``rfnd_``,
``pyt_``, ``sell_``, ``plat_``, ``evt_``, ``acct_``, ``jrnl_``.
"""

from __future__ import annotations

import secrets

# Known prefixes used across Obol. The ledger mints jrnl_ and pyt_ ids and
# reads the rest off inbound events.
PREFIXES = {
    "charge": "chg",
    "refund": "rfnd",
    "payout": "pyt",
    "seller": "sell",
    "platform": "plat",
    "event": "evt",
    "account": "acct",
    "journal": "jrnl",
}


def new_id(kind: str, *, nbytes: int = 8) -> str:
    """Mint a new prefixed id for ``kind`` (a key of :data:`PREFIXES`)."""
    try:
        prefix = PREFIXES[kind]
    except KeyError as exc:  # pragma: no cover - programmer error
        raise ValueError(f"unknown id kind: {kind!r}") from exc
    return f"{prefix}_{secrets.token_hex(nbytes)}"


def journal_id() -> str:
    return new_id("journal")


def payout_batch_id() -> str:
    return new_id("payout")


def account_id_of(name: str) -> str:
    """Deterministic account id derived from a chart-of-accounts name.

    Account ids are stable and human-legible (they *are* the account name),
    e.g. ``acct_seller_payable:sell_atelier``.
    """
    return f"acct_{name}"
