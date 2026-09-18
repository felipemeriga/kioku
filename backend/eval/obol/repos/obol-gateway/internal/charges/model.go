// Package charges owns the Charge domain: the model, the in-memory repository,
// and the service that authorizes and settles a buyer payment. It computes fees
// via the pricing package, calls the mock processor, and (via the service)
// emits payment.authorized then payment.settled events for the ledger.
package charges

import (
	"time"

	"github.com/obol/obol-gateway/internal/money"
)

// Status is the lifecycle state of a charge (SPEC.md > Charge).
type Status string

const (
	StatusPending           Status = "pending"
	StatusAuthorized        Status = "authorized"
	StatusSettled           Status = "settled"
	StatusFailed            Status = "failed"
	StatusRefunded          Status = "refunded"
	StatusPartiallyRefunded Status = "partially_refunded"
)

// Charge is a buyer payment. Field names match SPEC.md exactly.
type Charge struct {
	ID             string      `json:"id"`
	PlatformID     string      `json:"platform_id"`
	SellerID       string      `json:"seller_id"`
	Amount         money.Money `json:"amount"`
	PlatformFee    money.Money `json:"platform_fee"`
	ProcessorFee   money.Money `json:"processor_fee"`
	Status         Status      `json:"status"`
	IdempotencyKey string      `json:"idempotency_key"`
	ProcessorRef   string      `json:"processor_ref"`
	CreatedAt      time.Time   `json:"created_at"`

	// AmountRefunded tracks cumulative refunds so the service can decide
	// between partially_refunded and refunded. It is not part of the SPEC core
	// fields but is a natural derived attribute the refund flow maintains.
	AmountRefunded money.Money `json:"amount_refunded"`
}

// SellerNet returns amount - platform_fee - processor_fee. It assumes all three
// share the charge currency (guaranteed by the service that builds the charge).
func (c Charge) SellerNet() money.Money {
	afterPlatform, _ := c.Amount.Sub(c.PlatformFee)
	net, _ := afterPlatform.Sub(c.ProcessorFee)
	return net
}

// RemainingRefundable returns amount - amount_refunded, the maximum that can
// still be refunded against this charge.
func (c Charge) RemainingRefundable() money.Money {
	if c.AmountRefunded.Currency == "" {
		return c.Amount
	}
	remaining, _ := c.Amount.Sub(c.AmountRefunded)
	return remaining
}
