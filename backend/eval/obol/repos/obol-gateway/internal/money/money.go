// Package money implements the canonical Obol Money type: an integer amount in
// minor units (e.g. cents) plus an ISO-4217 currency code. Money is NEVER
// represented as a float. All arithmetic is exact integer arithmetic and is
// only permitted between values of the same currency.
//
// See SPEC.md > Money for the authoritative rules this package implements.
package money

import (
	"errors"
	"fmt"
	"math/big"
	"strings"
)

var (
	// ErrCurrencyMismatch is returned when arithmetic is attempted between two
	// Money values of different currencies. Cross-currency math is rejected.
	ErrCurrencyMismatch = errors.New("money: currency mismatch")
	// ErrInvalidCurrency is returned when a currency code is not a plausible
	// ISO-4217 alphabetic code (three uppercase letters).
	ErrInvalidCurrency = errors.New("money: invalid currency code")
	// ErrNegativeAmount is returned by constructors that require a non-negative
	// amount (charges, refunds, payouts cannot be negative).
	ErrNegativeAmount = errors.New("money: amount must be non-negative")
)

// Money is a fixed-precision monetary value. The zero value has AmountMinor 0
// and an empty currency; it should not be used in arithmetic until a currency
// is set via one of the constructors.
//
// Field names (amount_minor, currency) mirror SPEC.md across every language.
type Money struct {
	AmountMinor int64  `json:"amount_minor"`
	Currency    string `json:"currency"`
}

// New constructs a Money value, validating the currency code. The amount may be
// negative (useful for internal contra/offset values); use NewNonNegative for
// externally-supplied amounts.
func New(amountMinor int64, currency string) (Money, error) {
	c, err := normalizeCurrency(currency)
	if err != nil {
		return Money{}, err
	}
	return Money{AmountMinor: amountMinor, Currency: c}, nil
}

// NewNonNegative constructs a Money value and rejects negative amounts. This is
// the constructor to use for request-supplied charge / refund / payout amounts.
func NewNonNegative(amountMinor int64, currency string) (Money, error) {
	if amountMinor < 0 {
		return Money{}, ErrNegativeAmount
	}
	return New(amountMinor, currency)
}

// MustNew is a convenience constructor for tests and fixed sample data. It
// panics on an invalid currency and must not be used on untrusted input.
func MustNew(amountMinor int64, currency string) Money {
	m, err := New(amountMinor, currency)
	if err != nil {
		panic(err)
	}
	return m
}

// Zero returns a zero-amount Money in the given currency.
func Zero(currency string) (Money, error) { return New(0, currency) }

// IsZero reports whether the amount is exactly zero.
func (m Money) IsZero() bool { return m.AmountMinor == 0 }

// IsNegative reports whether the amount is below zero.
func (m Money) IsNegative() bool { return m.AmountMinor < 0 }

// SameCurrency reports whether two Money values share a currency.
func (m Money) SameCurrency(o Money) bool { return m.Currency == o.Currency }

func (m Money) assertSame(o Money) error {
	if m.Currency != o.Currency {
		return fmt.Errorf("%w: %s vs %s", ErrCurrencyMismatch, m.Currency, o.Currency)
	}
	return nil
}

// Add returns m + o. Both operands must share a currency.
func (m Money) Add(o Money) (Money, error) {
	if err := m.assertSame(o); err != nil {
		return Money{}, err
	}
	return Money{AmountMinor: m.AmountMinor + o.AmountMinor, Currency: m.Currency}, nil
}

// Sub returns m - o. Both operands must share a currency.
func (m Money) Sub(o Money) (Money, error) {
	if err := m.assertSame(o); err != nil {
		return Money{}, err
	}
	return Money{AmountMinor: m.AmountMinor - o.AmountMinor, Currency: m.Currency}, nil
}

// Cmp compares m and o, returning -1, 0, or +1. It errors on currency mismatch.
func (m Money) Cmp(o Money) (int, error) {
	if err := m.assertSame(o); err != nil {
		return 0, err
	}
	switch {
	case m.AmountMinor < o.AmountMinor:
		return -1, nil
	case m.AmountMinor > o.AmountMinor:
		return 1, nil
	default:
		return 0, nil
	}
}

// GreaterThan reports whether m > o (same currency required).
func (m Money) GreaterThan(o Money) (bool, error) {
	c, err := m.Cmp(o)
	return c > 0, err
}

// LessThan reports whether m < o (same currency required).
func (m Money) LessThan(o Money) (bool, error) {
	c, err := m.Cmp(o)
	return c < 0, err
}

// String renders the value for logs, e.g. "12000 EUR".
func (m Money) String() string {
	return fmt.Sprintf("%d %s", m.AmountMinor, m.Currency)
}

// ApplyBps multiplies the amount by a basis-point rate and rounds the result to
// the nearest minor unit using banker's rounding (round half to even).
//
//	result = round_half_even(amount * bps / 10000)
//
// This is the exact rule SPEC.md gives for platform_fee. It is exposed here (in
// addition to the pricing package) because it is a pure Money operation.
func (m Money) ApplyBps(bps int64) Money {
	rounded := RoundHalfEven(m.AmountMinor, bps, 10000)
	return Money{AmountMinor: rounded, Currency: m.Currency}
}

// RoundHalfEven computes round_half_even(value * mul / div) exactly using
// big.Int so no floating-point error is ever introduced. div must be > 0.
//
// "Round half to even" (banker's rounding) means a value exactly halfway
// between two integers rounds to the even one: 2.5 -> 2, 3.5 -> 4, -2.5 -> -2.
func RoundHalfEven(value, mul, div int64) int64 {
	if div == 0 {
		panic("money: division by zero in RoundHalfEven")
	}
	num := new(big.Int).Mul(big.NewInt(value), big.NewInt(mul))
	den := big.NewInt(div)

	quo := new(big.Int)
	rem := new(big.Int)
	quo.QuoRem(num, den, rem) // truncated toward zero; rem has sign of num

	if rem.Sign() == 0 {
		return quo.Int64()
	}

	// Compare 2*|rem| against |den| to decide rounding direction.
	twiceRem := new(big.Int).Abs(rem)
	twiceRem.Lsh(twiceRem, 1) // *2
	absDen := new(big.Int).Abs(den)

	cmp := twiceRem.Cmp(absDen)

	// Direction to round away from zero (matches sign of the true quotient).
	away := int64(1)
	if (num.Sign() < 0) != (den.Sign() < 0) {
		away = -1
	}

	switch {
	case cmp < 0:
		// Fractional part < 0.5 -> truncated quotient already correct.
		return quo.Int64()
	case cmp > 0:
		// Fractional part > 0.5 -> round away from zero.
		return quo.Int64() + away
	default:
		// Exactly 0.5 -> round to even.
		if quo.Bit(0) == 0 {
			return quo.Int64() // already even
		}
		return quo.Int64() + away
	}
}

func normalizeCurrency(currency string) (string, error) {
	c := strings.ToUpper(strings.TrimSpace(currency))
	if len(c) != 3 {
		return "", fmt.Errorf("%w: %q", ErrInvalidCurrency, currency)
	}
	for _, r := range c {
		if r < 'A' || r > 'Z' {
			return "", fmt.Errorf("%w: %q", ErrInvalidCurrency, currency)
		}
	}
	return c, nil
}
