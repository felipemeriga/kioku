"""The Obol chart of accounts (SPEC "Ledger model").

Five account families:

- ``processor_clearing``          (asset)     — money in transit from processor
- ``platform_revenue``            (revenue)   — accumulated platform fees
- ``processor_fees``              (expense)   — fees paid to the processor
- ``seller_payable:{seller_id}``  (liability) — what Obol owes each seller
- ``platform_reserve:{platform_id}`` (liability) — held funds / risk reserve

The first three are singletons; the last two are per-entity, keyed by a suffix
after a colon.
"""

from __future__ import annotations

from ..errors import PostingError
from ..models.account import AccountType

# Singleton account names.
PROCESSOR_CLEARING = "processor_clearing"
PLATFORM_REVENUE = "platform_revenue"
PROCESSOR_FEES = "processor_fees"

# Per-entity account name prefixes.
SELLER_PAYABLE = "seller_payable"
PLATFORM_RESERVE = "platform_reserve"

_SINGLETON_TYPES: dict[str, AccountType] = {
    PROCESSOR_CLEARING: AccountType.ASSET,
    PLATFORM_REVENUE: AccountType.REVENUE,
    PROCESSOR_FEES: AccountType.EXPENSE,
}

_PREFIX_TYPES: dict[str, AccountType] = {
    SELLER_PAYABLE: AccountType.LIABILITY,
    PLATFORM_RESERVE: AccountType.LIABILITY,
}


def seller_payable_account(seller_id: str) -> str:
    """Return the ``seller_payable:{seller_id}`` account name."""
    return f"{SELLER_PAYABLE}:{seller_id}"


def platform_reserve_account(platform_id: str) -> str:
    """Return the ``platform_reserve:{platform_id}`` account name."""
    return f"{PLATFORM_RESERVE}:{platform_id}"


def account_type_for(name: str) -> AccountType:
    """Resolve the :class:`AccountType` for any chart-of-accounts name.

    Handles both singletons (exact match) and per-entity accounts (``prefix:id``).
    Raises :class:`PostingError` for names outside the chart.
    """
    if name in _SINGLETON_TYPES:
        return _SINGLETON_TYPES[name]
    prefix = name.split(":", 1)[0]
    if prefix in _PREFIX_TYPES:
        return _PREFIX_TYPES[prefix]
    raise PostingError(f"unknown account in chart of accounts: {name!r}")
