// Package pricing is the single ground-truth location for Obol fee computation.
// Tests across the ecosystem reference this package. It computes the two fees a
// charge carries:
//
//   - platform_fee: the marketplace's cut, derived from a basis-point rate.
//     platform_fee = round_half_even(amount * platform_fee_bps / 10000)
//
//   - processor_fee: what the card network charges Obol, modeled here as a
//     bps component plus a fixed per-transaction minor-unit amount.
//     processor_fee = round_half_even(amount * processor_fee_bps / 10000) + fixed
//
// Both fees are in the same currency as the charge amount. The seller's net is
// amount - platform_fee - processor_fee and is derived downstream (in the
// charges service and, authoritatively for accounting, in the ledger).
//
// See SPEC.md > Money and SPEC.md > "Fee: computed vs recorded".
package pricing

import (
	"fmt"

	"github.com/obol/obol-gateway/internal/money"
)

// ProcessorFeeSchedule describes the mock processor's own pricing. A typical
// card fee is "1.5% + €0.25", encoded as Bps=150, FixedMinor=25.
type ProcessorFeeSchedule struct {
	Bps        int64
	FixedMinor int64
}

// Pricer computes fees for charges. It is stateless and safe for concurrent use.
type Pricer struct {
	// defaultPlatformFeeBps is used when a per-charge override is not supplied.
	defaultPlatformFeeBps int64
	processor             ProcessorFeeSchedule
}

// NewPricer builds a Pricer. defaultPlatformFeeBps must be >= 0.
func NewPricer(defaultPlatformFeeBps int64, processor ProcessorFeeSchedule) (*Pricer, error) {
	if defaultPlatformFeeBps < 0 {
		return nil, fmt.Errorf("pricing: defaultPlatformFeeBps must be >= 0, got %d", defaultPlatformFeeBps)
	}
	if processor.Bps < 0 || processor.FixedMinor < 0 {
		return nil, fmt.Errorf("pricing: processor fee components must be >= 0")
	}
	return &Pricer{defaultPlatformFeeBps: defaultPlatformFeeBps, processor: processor}, nil
}

// Quote is the fully-computed fee breakdown for a charge.
type Quote struct {
	Amount         money.Money // the gross charge amount
	PlatformFee    money.Money // marketplace's cut
	ProcessorFee   money.Money // card network's cut
	SellerNet      money.Money // amount - platform_fee - processor_fee
	PlatformFeeBps int64       // the bps rate actually applied
}

// PlatformFee computes the platform fee for an amount at a given bps rate. This
// is the canonical implementation of the SPEC rule:
//
//	platform_fee = round_half_even(amount * platform_fee_bps / 10000)
func PlatformFee(amount money.Money, platformFeeBps int64) money.Money {
	return amount.ApplyBps(platformFeeBps)
}

// PlatformFeeBps returns the bps rate the Pricer will apply given an optional
// per-charge override. A nil override falls back to the platform default.
func (p *Pricer) PlatformFeeBps(overrideBps *int64) int64 {
	if overrideBps != nil && *overrideBps >= 0 {
		return *overrideBps
	}
	return p.defaultPlatformFeeBps
}

// ProcessorFee computes the processor fee for an amount using this Pricer's
// schedule: round_half_even(amount*bps/10000) + fixed, in the same currency.
func (p *Pricer) ProcessorFee(amount money.Money) money.Money {
	pct := amount.ApplyBps(p.processor.Bps)
	fixed := money.Money{AmountMinor: p.processor.FixedMinor, Currency: amount.Currency}
	// Same-currency by construction; the error is impossible here.
	sum, _ := pct.Add(fixed)
	return sum
}

// Quote computes the full fee breakdown for a charge amount. overrideBps, when
// non-nil and non-negative, replaces the platform default fee rate for this one
// charge (e.g. a negotiated rate for a specific seller).
func (p *Pricer) Quote(amount money.Money, overrideBps *int64) (Quote, error) {
	if amount.IsNegative() {
		return Quote{}, fmt.Errorf("pricing: charge amount must be non-negative, got %s", amount)
	}

	bps := p.PlatformFeeBps(overrideBps)
	platformFee := PlatformFee(amount, bps)
	processorFee := p.ProcessorFee(amount)

	afterPlatform, err := amount.Sub(platformFee)
	if err != nil {
		return Quote{}, err
	}
	sellerNet, err := afterPlatform.Sub(processorFee)
	if err != nil {
		return Quote{}, err
	}

	return Quote{
		Amount:         amount,
		PlatformFee:    platformFee,
		ProcessorFee:   processorFee,
		SellerNet:      sellerNet,
		PlatformFeeBps: bps,
	}, nil
}
