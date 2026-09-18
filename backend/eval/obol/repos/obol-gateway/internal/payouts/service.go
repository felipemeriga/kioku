package payouts

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/obol/obol-gateway/internal/directory"
	"github.com/obol/obol-gateway/internal/events"
	"github.com/obol/obol-gateway/internal/ids"
	"github.com/obol/obol-gateway/internal/money"
	"github.com/obol/obol-gateway/internal/processor"
)

// Domain errors surfaced by the payout service.
var (
	ErrCurrencyMismatch  = errors.New("payouts: payout currency must match seller payout currency")
	ErrDeclined          = errors.New("payouts: processor declined the payout")
	ErrSellerNotVerified = errors.New("payouts: seller is not KYC-verified")
)

// ExecuteInput is the validated request to execute a seller payout. This is
// typically called by the ledger's payout-batch builder after it has drawn down
// the seller's payable balance.
type ExecuteInput struct {
	// BatchID lets the caller (the ledger) supply the batch id it already
	// created; if empty, the gateway mints one.
	BatchID      string
	SellerID     string
	Amount       money.Money
	Descriptor   string
	ScheduledFor time.Time
}

// Service executes payouts via the processor and emits payout events.
type Service struct {
	repo      Repository
	proc      processor.Processor
	publisher events.Publisher
	dir       *directory.Directory
	now       func() time.Time
}

// NewService wires a payout service. now may be nil (defaults to time.Now UTC).
func NewService(
	repo Repository,
	proc processor.Processor,
	publisher events.Publisher,
	dir *directory.Directory,
	now func() time.Time,
) *Service {
	if now == nil {
		now = func() time.Time { return time.Now().UTC() }
	}
	return &Service{repo: repo, proc: proc, publisher: publisher, dir: dir, now: now}
}

// Execute runs the payout flow:
//
//  1. validate the seller and the payout currency,
//  2. persist the batch as processing and emit payout.scheduled,
//  3. call processor.Payout to move funds to the seller's bank,
//  4. on success mark the batch paid and emit payout.paid — the ledger marks
//     the batch paid and debits seller_payable off this event.
func (s *Service) Execute(ctx context.Context, in ExecuteInput) (PayoutBatch, error) {
	seller, err := s.dir.Seller(in.SellerID)
	if err != nil {
		return PayoutBatch{}, err
	}
	if seller.KYCStatus != directory.KYCVerified {
		return PayoutBatch{}, ErrSellerNotVerified
	}
	if in.Amount.Currency != seller.PayoutCurrency {
		return PayoutBatch{}, fmt.Errorf("%w: payout %s vs seller %s",
			ErrCurrencyMismatch, in.Amount.Currency, seller.PayoutCurrency)
	}

	batchID := in.BatchID
	if batchID == "" {
		batchID = ids.Payout()
	}
	scheduledFor := in.ScheduledFor
	if scheduledFor.IsZero() {
		scheduledFor = s.now()
	}

	batch := PayoutBatch{
		ID:           batchID,
		SellerID:     in.SellerID,
		Amount:       in.Amount,
		Status:       StatusProcessing,
		ScheduledFor: scheduledFor,
		CreatedAt:    s.now(),
	}
	if err := s.repo.Create(ctx, batch); err != nil {
		return PayoutBatch{}, err
	}

	// payout.scheduled — informational; the ledger already knows the batch.
	scheduled, err := events.PayoutScheduled(events.PayoutScheduledData{
		BatchID:      batch.ID,
		SellerID:     batch.SellerID,
		Amount:       batch.Amount,
		ScheduledFor: batch.ScheduledFor,
	})
	if err != nil {
		return PayoutBatch{}, err
	}
	if err := s.publisher.Publish(ctx, scheduled); err != nil {
		return batch, fmt.Errorf("payouts: publish scheduled: %w", err)
	}

	// Processor call — move the money.
	res, err := s.proc.Payout(ctx, processor.PayoutRequest{
		BatchID:    batch.ID,
		SellerID:   batch.SellerID,
		Amount:     batch.Amount,
		Descriptor: in.Descriptor,
	})
	if err != nil {
		batch.Status = StatusFailed
		_ = s.repo.Update(ctx, batch)
		if errors.Is(err, processor.ErrDeclined) {
			return batch, ErrDeclined
		}
		return batch, fmt.Errorf("payouts: processor error: %w", err)
	}

	batch.Status = StatusPaid
	batch.ProcessorRef = res.ProcessorRef
	if err := s.repo.Update(ctx, batch); err != nil {
		return PayoutBatch{}, err
	}

	// payout.paid — ledger marks the batch paid and debits seller_payable.
	paid, err := events.PayoutPaid(events.PayoutPaidData{
		BatchID:      batch.ID,
		SellerID:     batch.SellerID,
		Amount:       batch.Amount,
		ProcessorRef: batch.ProcessorRef,
	})
	if err != nil {
		return batch, err
	}
	if err := s.publisher.Publish(ctx, paid); err != nil {
		return batch, fmt.Errorf("payouts: publish paid: %w", err)
	}

	return batch, nil
}

// Get returns a batch by id.
func (s *Service) Get(ctx context.Context, id string) (PayoutBatch, error) {
	return s.repo.Get(ctx, id)
}
