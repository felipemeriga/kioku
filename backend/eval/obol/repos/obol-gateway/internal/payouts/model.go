// Package payouts owns payout execution. The ledger builds a batch from a
// seller's payable balance and calls the gateway's POST /v1/payouts to actually
// move money; this service calls processor.Payout and, on success, emits
// payout.paid (and payout.scheduled) for the ledger to reconcile
// (SPEC.md > cross-repo relationship #4).
package payouts

import (
	"time"

	"github.com/obol/obol-gateway/internal/money"
)

// Status is the lifecycle state of a payout batch (SPEC.md > PayoutBatch).
type Status string

const (
	StatusScheduled  Status = "scheduled"
	StatusProcessing Status = "processing"
	StatusPaid       Status = "paid"
	StatusFailed     Status = "failed"
)

// PayoutBatch is a scheduled movement of a seller's balance to their bank.
// Field names match SPEC.md.
type PayoutBatch struct {
	ID           string      `json:"id"`
	SellerID     string      `json:"seller_id"`
	Amount       money.Money `json:"amount"`
	Status       Status      `json:"status"`
	ScheduledFor time.Time   `json:"scheduled_for"`
	ProcessorRef string      `json:"processor_ref"`
	CreatedAt    time.Time   `json:"created_at"`
}
