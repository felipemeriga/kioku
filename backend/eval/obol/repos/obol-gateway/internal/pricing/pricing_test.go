package pricing

import (
	"testing"

	"github.com/obol/obol-gateway/internal/money"
)

// The canonical sample charge chg_0001 from SPEC.md:
//   amount €120.00 (12000), platform_fee €3.48 (348), processor_fee 205,
//   seller net €114.47 (11447).
// The platform runs at 290 bps (2.9%). The processor fee 205 for a €120.00
// charge is 1.5% + €0.25 = 180 + 25 = 205, which is how the mock is configured.

func TestPlatformFeeChg0001(t *testing.T) {
	amount := money.MustNew(12000, "EUR")
	fee := PlatformFee(amount, 290)
	if fee.AmountMinor != 348 {
		t.Fatalf("platform_fee = %d, want 348", fee.AmountMinor)
	}
}

func TestQuoteChg0001(t *testing.T) {
	p, err := NewPricer(290, ProcessorFeeSchedule{Bps: 150, FixedMinor: 25})
	if err != nil {
		t.Fatal(err)
	}
	q, err := p.Quote(money.MustNew(12000, "EUR"), nil)
	if err != nil {
		t.Fatal(err)
	}
	if q.PlatformFee.AmountMinor != 348 {
		t.Errorf("platform_fee = %d, want 348", q.PlatformFee.AmountMinor)
	}
	if q.ProcessorFee.AmountMinor != 205 {
		t.Errorf("processor_fee = %d, want 205", q.ProcessorFee.AmountMinor)
	}
	if q.SellerNet.AmountMinor != 11447 {
		t.Errorf("seller_net = %d, want 11447", q.SellerNet.AmountMinor)
	}
	if q.PlatformFeeBps != 290 {
		t.Errorf("platform_fee_bps = %d, want 290", q.PlatformFeeBps)
	}
}

func TestQuoteOverrideBps(t *testing.T) {
	p, _ := NewPricer(290, ProcessorFeeSchedule{Bps: 150, FixedMinor: 25})
	override := int64(100) // 1.0%
	q, err := p.Quote(money.MustNew(12000, "EUR"), &override)
	if err != nil {
		t.Fatal(err)
	}
	if q.PlatformFeeBps != 100 {
		t.Fatalf("override bps = %d, want 100", q.PlatformFeeBps)
	}
	if q.PlatformFee.AmountMinor != 120 { // 1% of 12000
		t.Fatalf("platform_fee = %d, want 120", q.PlatformFee.AmountMinor)
	}
}

func TestQuoteRejectsNegative(t *testing.T) {
	p, _ := NewPricer(290, ProcessorFeeSchedule{Bps: 150, FixedMinor: 25})
	if _, err := p.Quote(money.Money{AmountMinor: -1, Currency: "EUR"}, nil); err == nil {
		t.Fatal("expected error for negative amount")
	}
}
