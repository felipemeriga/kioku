"""Money arithmetic + banker's rounding."""

import pytest

from obol_ledger.errors import CurrencyMismatchError, InvalidMoneyError
from obol_ledger.money import Money, round_half_even, sum_money


def test_add_and_sub_same_currency():
    a = Money.of(12000, "EUR")
    b = Money.of(348, "EUR")
    assert (a - b).amount_minor == 11652
    assert (a + b).amount_minor == 12348


def test_cross_currency_rejected():
    with pytest.raises(CurrencyMismatchError):
        _ = Money.of(100, "EUR") + Money.of(100, "USD")
    with pytest.raises(CurrencyMismatchError):
        _ = Money.of(100, "EUR") - Money.of(100, "USD")


def test_currency_is_normalized_and_validated():
    assert Money.of(1, "eur").currency == "EUR"
    with pytest.raises(InvalidMoneyError):
        Money.of(1, "E1R")


def test_bps_fee_banker_rounding():
    # 12000 * 290 / 10000 = 348.0 exactly -> 348
    assert Money.of(12000, "EUR").mul_bps(290).amount_minor == 348


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0.5", 0),  # ties to even -> 0
        ("1.5", 2),  # ties to even -> 2
        ("2.5", 2),  # ties to even -> 2
        ("2.4", 2),
        ("2.6", 3),
    ],
)
def test_round_half_even(value, expected):
    from decimal import Decimal

    assert round_half_even(Decimal(value)) == expected


def test_sum_money_from_zero():
    total = sum_money([Money.of(348, "EUR"), Money.of(205, "EUR"), Money.of(11447, "EUR")], "EUR")
    assert total.amount_minor == 12000


def test_format():
    assert Money.of(12000, "EUR").format() == "120.00 EUR"
    assert Money.of(-205, "EUR").format() == "-2.05 EUR"


def test_money_is_frozen():
    m = Money.of(100, "EUR")
    with pytest.raises(Exception):
        m.amount_minor = 200  # type: ignore[misc]
