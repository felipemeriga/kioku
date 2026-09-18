"""The :class:`Money` value object.

Money is ALWAYS integer minor units + an ISO-4217 currency (see SPEC "Money").
Never floats. Arithmetic is only permitted between same-currency values;
cross-currency operations raise :class:`CurrencyMismatchError`.

Fee rounding uses banker's rounding (round-half-to-even), matching the SPEC
rule ``platform_fee = round_half_even(charge_amount * bps / 10000)``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .errors import CurrencyMismatchError, InvalidMoneyError


def round_half_even(value: Decimal) -> int:
    """Round a Decimal to the nearest integer using banker's rounding."""
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


class Money(BaseModel):
    """An immutable amount of money: integer minor units + currency.

    Field names (``amount_minor``, ``currency``) are identical across all Obol
    repos per the canonical spec.
    """

    model_config = ConfigDict(frozen=True)

    amount_minor: int = Field(..., description="Integer minor units, e.g. cents.")
    currency: str = Field(..., min_length=3, max_length=3, description="ISO-4217 code.")

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.isalpha() or len(v) != 3:
            raise InvalidMoneyError(f"invalid currency code: {v!r}")
        return v

    # -- construction helpers -------------------------------------------------

    @classmethod
    def zero(cls, currency: str) -> "Money":
        """A zero amount in ``currency`` — the additive identity."""
        return cls(amount_minor=0, currency=currency)

    @classmethod
    def of(cls, amount_minor: int, currency: str) -> "Money":
        """Terse constructor: ``Money.of(4999, "USD")``."""
        return cls(amount_minor=amount_minor, currency=currency)

    # -- invariants -----------------------------------------------------------

    def _assert_same_currency(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                f"cannot combine {self.currency} with {other.currency}"
            )

    # -- arithmetic (same-currency only) --------------------------------------

    def __add__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(amount_minor=self.amount_minor + other.amount_minor, currency=self.currency)

    def __sub__(self, other: "Money") -> "Money":
        self._assert_same_currency(other)
        return Money(amount_minor=self.amount_minor - other.amount_minor, currency=self.currency)

    def __neg__(self) -> "Money":
        return Money(amount_minor=-self.amount_minor, currency=self.currency)

    def mul_bps(self, bps: int) -> "Money":
        """Multiply by a basis-point rate with banker's rounding.

        ``1 bps = 0.01%``; a 2.9% fee is ``290`` bps. Used for fee computation:
        ``platform_fee = round_half_even(amount * bps / 10000)``.
        """
        raw = Decimal(self.amount_minor) * Decimal(bps) / Decimal(10000)
        return Money(amount_minor=round_half_even(raw), currency=self.currency)

    # -- comparisons ----------------------------------------------------------

    def __lt__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount_minor < other.amount_minor

    def __le__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount_minor <= other.amount_minor

    def __gt__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount_minor > other.amount_minor

    def __ge__(self, other: "Money") -> bool:
        self._assert_same_currency(other)
        return self.amount_minor >= other.amount_minor

    # -- predicates -----------------------------------------------------------

    @property
    def is_zero(self) -> bool:
        return self.amount_minor == 0

    @property
    def is_positive(self) -> bool:
        return self.amount_minor > 0

    @property
    def is_negative(self) -> bool:
        return self.amount_minor < 0

    def abs(self) -> "Money":
        return Money(amount_minor=abs(self.amount_minor), currency=self.currency)

    # -- formatting -----------------------------------------------------------

    def format(self, minor_digits: int = 2) -> str:
        """Human-readable major-unit rendering, e.g. ``120.00 EUR``."""
        scale = 10**minor_digits
        whole, frac = divmod(abs(self.amount_minor), scale)
        sign = "-" if self.amount_minor < 0 else ""
        return f"{sign}{whole}.{frac:0{minor_digits}d} {self.currency}"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.format()


def sum_money(items: list[Money], currency: str) -> Money:
    """Sum a list of same-currency :class:`Money`, starting from zero.

    Raises :class:`CurrencyMismatchError` if any item disagrees with ``currency``.
    """
    total = Money.zero(currency)
    for item in items:
        total = total + item
    return total


def coerce_money(value: Any) -> Money:
    """Best-effort coercion of an inbound dict/Money into :class:`Money`."""
    if isinstance(value, Money):
        return value
    if isinstance(value, dict):
        return Money(amount_minor=int(value["amount_minor"]), currency=value["currency"])
    raise InvalidMoneyError(f"cannot coerce {value!r} to Money")
