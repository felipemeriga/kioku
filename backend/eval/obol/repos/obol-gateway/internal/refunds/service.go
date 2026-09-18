package refunds

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/obol/obol-gateway/internal/charges"
	"github.com/obol/obol-gateway/internal/events"
	"github.com/obol/obol-gateway/internal/ids"
	"github.com/obol/obol-gateway/internal/money"
	"github.com/obol/obol-gateway/internal/processor"
)

// Domain errors surfaced by the refund service.
var (
	ErrChargeNotSettled  = errors.New("refunds: only settled charges can be refunded")
	ErrExceedsRefundable = errors.New("refunds: amount exceeds remaining refundable balance")
	ErrCurrencyMismatch  = errors.New("refunds: refund currency must match charge currency")
	ErrProcessorFailed   = errors.New("refunds: processor refund failed")
)

// CreateInput is the validated request to refund a charge.
type CreateInput struct {
	ChargeID string
	Amount   money.Money
	Reason   string
}

// Service creates refunds. It is the seam between the charge repository, the
// processor adapter, and event publishing.
type Service struct {
	repo       Repository
	chargeRepo charges.Repository
	proc       processor.Processor
	publisher  events.Publisher
	now        func() time.Time
}

// NewService wires a refund service. now may be nil (defaults to time.Now UTC).
func NewService(
	repo Repository,
	chargeRepo charges.Repository,
	proc processor.Processor,
	publisher events.Publisher,
	now func() time.Time,
) *Service {
	if now == nil {
		now = func() time.Time { return time.Now().UTC() }
	}
	return &Service{repo: repo, chargeRepo: chargeRepo, proc: proc, publisher: publisher, now: now}
}

// Create refunds all or part of a charge:
//
//  1. load the charge and validate it is settled and has enough refundable left,
//  2. call processor.Refund against the original processor_ref,
//  3. persist the refund, advance the charge's refunded totals and status,
//  4. publish refund.completed — the ledger posts the reversal entry off this.
//
// This is the gateway half of the end-to-end refund flow that spans console,
// gateway, and ledger (SPEC.md > cross-repo relationship #1).
func (s *Service) Create(ctx context.Context, in CreateInput) (Refund, error) {
	charge, err := s.chargeRepo.Get(ctx, in.ChargeID)
	if err != nil {
		return Refund{}, err
	}

	if charge.Status != charges.StatusSettled &&
		charge.Status != charges.StatusPartiallyRefunded {
		return Refund{}, ErrChargeNotSettled
	}
	if in.Amount.Currency != charge.Amount.Currency {
		return Refund{}, fmt.Errorf("%w: refund %s vs charge %s",
			ErrCurrencyMismatch, in.Amount.Currency, charge.Amount.Currency)
	}

	remaining := charge.RemainingRefundable()
	if over, _ := in.Amount.GreaterThan(remaining); over {
		return Refund{}, fmt.Errorf("%w: requested %s, remaining %s",
			ErrExceedsRefundable, in.Amount, remaining)
	}

	refundID := ids.Refund()

	// Processor call — reverse funds at the card network.
	res, err := s.proc.Refund(ctx, processor.RefundRequest{
		RefundID:    refundID,
		OriginalRef: charge.ProcessorRef,
		Amount:      in.Amount,
		Reason:      in.Reason,
	})
	if err != nil {
		failed := Refund{
			ID: refundID, ChargeID: in.ChargeID, Amount: in.Amount,
			Reason: in.Reason, Status: StatusFailed, CreatedAt: s.now(),
		}
		_ = s.repo.Create(ctx, failed)
		return failed, fmt.Errorf("%w: %v", ErrProcessorFailed, err)
	}

	refund := Refund{
		ID:           refundID,
		ChargeID:     in.ChargeID,
		Amount:       in.Amount,
		Reason:       in.Reason,
		Status:       StatusCompleted,
		ProcessorRef: res.ProcessorRef,
		CreatedAt:    s.now(),
	}
	if err := s.repo.Create(ctx, refund); err != nil {
		return Refund{}, err
	}

	// Advance the charge's refunded total and derive its new status.
	if err := s.advanceCharge(ctx, charge, in.Amount); err != nil {
		return Refund{}, err
	}

	// Publish refund.completed — ledger posts the reversal entry.
	env, err := events.RefundCompleted(events.RefundData{
		RefundID: refund.ID,
		ChargeID: refund.ChargeID,
		Amount:   refund.Amount,
	})
	if err != nil {
		return refund, err
	}
	if err := s.publisher.Publish(ctx, env); err != nil {
		return refund, fmt.Errorf("refunds: event publish failed: %w", err)
	}

	return refund, nil
}

// advanceCharge updates amount_refunded and flips the charge to refunded or
// partially_refunded.
func (s *Service) advanceCharge(ctx context.Context, charge charges.Charge, refundAmount money.Money) error {
	prior := charge.AmountRefunded
	if prior.Currency == "" {
		prior, _ = money.Zero(charge.Amount.Currency)
	}
	total, err := prior.Add(refundAmount)
	if err != nil {
		return err
	}
	charge.AmountRefunded = total

	if eq, _ := total.Cmp(charge.Amount); eq >= 0 {
		charge.Status = charges.StatusRefunded
	} else {
		charge.Status = charges.StatusPartiallyRefunded
	}
	return s.chargeRepo.Update(ctx, charge)
}

// Get returns a refund by id.
func (s *Service) Get(ctx context.Context, id string) (Refund, error) {
	return s.repo.Get(ctx, id)
}
