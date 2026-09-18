"""In-memory account registry.

Accounts are created lazily on first reference (posting to
``seller_payable:sell_atelier`` auto-provisions it) but the singleton accounts
are seeded up front so a fresh ledger has a complete chart from boot.
"""

from __future__ import annotations

from ..config import get_settings
from ..models.account import Account
from .chart import (
    PLATFORM_REVENUE,
    PROCESSOR_CLEARING,
    PROCESSOR_FEES,
    account_type_for,
)


class AccountRegistry:
    """Ensures accounts exist and resolves them by canonical name."""

    def __init__(self, default_currency: str | None = None) -> None:
        self._default_currency = default_currency or get_settings().default_currency
        self._accounts: dict[str, Account] = {}
        self._seed_singletons()

    def _seed_singletons(self) -> None:
        for name in (PROCESSOR_CLEARING, PLATFORM_REVENUE, PROCESSOR_FEES):
            self.ensure(name)

    def ensure(self, name: str, currency: str | None = None) -> Account:
        """Return the account for ``name``, creating it if it does not exist."""
        existing = self._accounts.get(name)
        if existing is not None:
            return existing
        account = Account.create(
            name=name,
            type=account_type_for(name),
            currency=currency or self._default_currency,
            description=_describe(name),
        )
        self._accounts[name] = account
        return account

    def get(self, name: str) -> Account | None:
        return self._accounts.get(name)

    def all(self) -> list[Account]:
        return list(self._accounts.values())

    def names(self) -> list[str]:
        return list(self._accounts.keys())


def _describe(name: str) -> str:
    prefix = name.split(":", 1)[0]
    return {
        PROCESSOR_CLEARING: "Money in transit from the card processor.",
        PLATFORM_REVENUE: "Accumulated platform fees.",
        PROCESSOR_FEES: "Fees paid to the processor.",
        "seller_payable": "Liability: funds owed to a seller.",
        "platform_reserve": "Liability: held funds / risk reserve for a platform.",
    }.get(name, {}.get(prefix, ""))
