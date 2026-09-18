// Package refunds owns the Refund domain: model, repository, and the service
// that reverses all or part of a charge. The service calls processor.Refund
// then publishes refund.completed for the ledger to post the reversal entry
// (SPEC.md > cross-repo relationship #1).
package refunds

import (
	"time"

	"github.com/obol/obol-gateway/internal/money"
)

// Status is the lifecycle state of a refund (SPEC.md > Refund).
type Status string

const (
	StatusPending   Status = "pending"
	StatusCompleted Status = "completed"
	StatusFailed    Status = "failed"
)

// Refund reverses all or part of a charge. Field names match SPEC.md.
type Refund struct {
	ID           string      `json:"id"`
	ChargeID     string      `json:"charge_id"`
	Amount       money.Money `json:"amount"`
	Reason       string      `json:"reason"`
	Status       Status      `json:"status"`
	ProcessorRef string      `json:"processor_ref"`
	CreatedAt    time.Time   `json:"created_at"`
}
