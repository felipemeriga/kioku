// Package processor is the ground-truth mock card-processor adapter. It stands
// in for the real "card network" and exposes the three money-movement
// operations Obol needs: Charge (authorize+capture), Refund, and Payout.
//
// The mock is deterministic: the outcome (approved/declined) and the returned
// processor reference are a pure function of the inputs, so tests and the
// ecosystem's fixed sample data (chg_0001, etc.) line up every run. Nothing
// here touches a real network.
//
// See SPEC.md > obol-gateway ground-truth locations: processor adapter.
package processor

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"

	"github.com/obol/obol-gateway/internal/money"
)

// Outcome enumerates the terminal states a processor operation can reach.
type Outcome string

const (
	OutcomeApproved Outcome = "approved"
	OutcomeDeclined Outcome = "declined"
)

// ErrDeclined is returned by the adapter when the processor declines an
// operation. Handlers map this to a 402 Payment Required.
var ErrDeclined = errors.New("processor: operation declined")

// ChargeRequest asks the processor to authorize and capture a card payment.
type ChargeRequest struct {
	ChargeID   string      // Obol charge id, used to derive a deterministic ref
	Amount     money.Money // gross amount to charge the buyer
	CardToken  string      // opaque tokenized instrument (mocked)
	Descriptor string      // statement descriptor shown to the buyer
}

// ChargeResult is the processor's answer to a ChargeRequest.
type ChargeResult struct {
	Outcome      Outcome
	ProcessorRef string // e.g. "pi_<hash>" — the network's own reference
}

// RefundRequest asks the processor to reverse all or part of a prior charge.
type RefundRequest struct {
	RefundID    string      // Obol refund id
	OriginalRef string      // processor_ref of the original charge
	Amount      money.Money // amount to refund (<= original charge)
	Reason      string
}

// RefundResult is the processor's answer to a RefundRequest.
type RefundResult struct {
	Outcome      Outcome
	ProcessorRef string // e.g. "re_<hash>"
}

// PayoutRequest asks the processor to move a seller's funds to their bank.
type PayoutRequest struct {
	BatchID    string      // Obol payout batch id
	SellerID   string      // recipient seller
	Amount     money.Money // payout amount
	Descriptor string
}

// PayoutResult is the processor's answer to a PayoutRequest.
type PayoutResult struct {
	Outcome      Outcome
	ProcessorRef string // e.g. "po_<hash>"
}

// Processor is the adapter interface the gateway depends on. Swapping in a real
// card-network client means implementing this interface.
type Processor interface {
	Charge(ctx context.Context, req ChargeRequest) (ChargeResult, error)
	Refund(ctx context.Context, req RefundRequest) (RefundResult, error)
	Payout(ctx context.Context, req PayoutRequest) (PayoutResult, error)
}

// Mock is the deterministic in-memory Processor used in development and tests.
type Mock struct {
	// DeclineOverAmountMinor, when > 0, declines any single operation whose
	// amount is strictly greater than this threshold (models a card limit).
	DeclineOverAmountMinor int64
}

// NewMock returns a Mock that approves everything by default.
func NewMock() *Mock { return &Mock{} }

// Charge implements Processor. It approves unless the amount exceeds the
// configured decline threshold, and returns a deterministic "pi_" reference.
func (m *Mock) Charge(_ context.Context, req ChargeRequest) (ChargeResult, error) {
	if req.Amount.IsNegative() || req.Amount.IsZero() {
		return ChargeResult{}, fmt.Errorf("processor: charge amount must be positive, got %s", req.Amount)
	}
	if m.declines(req.Amount.AmountMinor) {
		return ChargeResult{Outcome: OutcomeDeclined}, ErrDeclined
	}
	return ChargeResult{
		Outcome:      OutcomeApproved,
		ProcessorRef: ref("pi", req.ChargeID, req.Amount),
	}, nil
}

// Refund implements Processor. It always approves (a refund of an approved
// charge never bounces in the mock) and returns a deterministic "re_" ref.
func (m *Mock) Refund(_ context.Context, req RefundRequest) (RefundResult, error) {
	if req.Amount.IsNegative() || req.Amount.IsZero() {
		return RefundResult{}, fmt.Errorf("processor: refund amount must be positive, got %s", req.Amount)
	}
	if req.OriginalRef == "" {
		return RefundResult{}, errors.New("processor: refund requires the original charge ref")
	}
	return RefundResult{
		Outcome:      OutcomeApproved,
		ProcessorRef: ref("re", req.RefundID, req.Amount),
	}, nil
}

// Payout implements Processor. It approves unless the amount exceeds the
// configured decline threshold, and returns a deterministic "po_" ref.
func (m *Mock) Payout(_ context.Context, req PayoutRequest) (PayoutResult, error) {
	if req.Amount.IsNegative() || req.Amount.IsZero() {
		return PayoutResult{}, fmt.Errorf("processor: payout amount must be positive, got %s", req.Amount)
	}
	if m.declines(req.Amount.AmountMinor) {
		return PayoutResult{Outcome: OutcomeDeclined}, ErrDeclined
	}
	return PayoutResult{
		Outcome:      OutcomeApproved,
		ProcessorRef: ref("po", req.BatchID, req.Amount),
	}, nil
}

func (m *Mock) declines(amountMinor int64) bool {
	return m.DeclineOverAmountMinor > 0 && amountMinor > m.DeclineOverAmountMinor
}

// ref builds a deterministic processor reference from a prefix, an id, and an
// amount. Given identical inputs it always returns the same reference, which is
// what makes the sample data reproducible.
func ref(prefix, id string, amount money.Money) string {
	h := sha256.Sum256([]byte(fmt.Sprintf("%s|%s|%d|%s", prefix, id, amount.AmountMinor, amount.Currency)))
	return prefix + "_" + hex.EncodeToString(h[:8])
}

// Ensure Mock satisfies Processor at compile time.
var _ Processor = (*Mock)(nil)
