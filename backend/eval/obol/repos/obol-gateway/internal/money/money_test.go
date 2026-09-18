package money

import "testing"

func TestAddSameCurrency(t *testing.T) {
	a := MustNew(12000, "EUR")
	b := MustNew(348, "EUR")
	got, err := a.Add(b)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got.AmountMinor != 12348 || got.Currency != "EUR" {
		t.Fatalf("Add = %v, want 12348 EUR", got)
	}
}

func TestAddCrossCurrencyRejected(t *testing.T) {
	a := MustNew(100, "EUR")
	b := MustNew(100, "USD")
	if _, err := a.Add(b); err == nil {
		t.Fatal("expected ErrCurrencyMismatch, got nil")
	}
}

func TestSub(t *testing.T) {
	// Seller net = amount - platform_fee - processor_fee for chg_0001.
	amount := MustNew(12000, "EUR")
	afterPlatform, err := amount.Sub(MustNew(348, "EUR"))
	if err != nil {
		t.Fatal(err)
	}
	net, err := afterPlatform.Sub(MustNew(205, "EUR"))
	if err != nil {
		t.Fatal(err)
	}
	if net.AmountMinor != 11447 {
		t.Fatalf("seller net = %d, want 11447", net.AmountMinor)
	}
}

func TestApplyBpsChg0001(t *testing.T) {
	// €120.00 at 290 bps (2.9%) = €3.48 exactly.
	amount := MustNew(12000, "EUR")
	fee := amount.ApplyBps(290)
	if fee.AmountMinor != 348 {
		t.Fatalf("platform_fee = %d, want 348", fee.AmountMinor)
	}
	if fee.Currency != "EUR" {
		t.Fatalf("currency = %s, want EUR", fee.Currency)
	}
}

func TestRoundHalfEven(t *testing.T) {
	cases := []struct {
		name            string
		value, mul, div int64
		want            int64
	}{
		{"exact", 12000, 290, 10000, 348},       // 348.0
		{"half_to_even_down", 5, 1, 2, 2},       // 2.5 -> 2
		{"half_to_even_up", 7, 1, 2, 4},         // 3.5 -> 4
		{"below_half", 4, 1, 3, 1},              // 1.333 -> 1
		{"above_half", 5, 1, 3, 2},              // 1.667 -> 2
		{"negative_half_to_even", -5, 1, 2, -2}, // -2.5 -> -2
		{"negative_above_half", -5, 1, 3, -2},   // -1.667 -> -2
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := RoundHalfEven(tc.value, tc.mul, tc.div)
			if got != tc.want {
				t.Fatalf("RoundHalfEven(%d,%d,%d) = %d, want %d",
					tc.value, tc.mul, tc.div, got, tc.want)
			}
		})
	}
}

func TestNewNonNegativeRejectsNegative(t *testing.T) {
	if _, err := NewNonNegative(-1, "EUR"); err == nil {
		t.Fatal("expected ErrNegativeAmount")
	}
}

func TestInvalidCurrency(t *testing.T) {
	if _, err := New(100, "EU"); err == nil {
		t.Fatal("expected ErrInvalidCurrency for 2-letter code")
	}
	if _, err := New(100, "eur"); err != nil {
		t.Fatalf("lowercase should normalize, got %v", err)
	}
}
