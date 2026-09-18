package charges

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/obol/obol-gateway/internal/directory"
	"github.com/obol/obol-gateway/internal/events"
	"github.com/obol/obol-gateway/internal/ids"
	"github.com/obol/obol-gateway/internal/money"
	"github.com/obol/obol-gateway/internal/pricing"
	"github.com/obol/obol-gateway/internal/processor"
)

// Domain errors surfaced by the charge service. The API layer maps these to
// HTTP status codes.
var (
	ErrSellerNotVerified = errors.New("charges: seller is not KYC-verified")
	ErrCurrencyMismatch  = errors.New("charges: charge currency must match seller payout currency")
	ErrDeclined          = errors.New("charges: processor declined the charge")
)

// CreateInput is the validated request to create (authorize + settle) a charge.
type CreateInput struct {
	PlatformID     string
	SellerID       string
	Amount         money.Money
	CardToken      string
	Descriptor     string
	IdempotencyKey string
	// PlatformFeeBpsOverride, when non-nil, overrides the platform default fee
	// rate for this single charge.
	PlatformFeeBpsOverride *int64
}

// Service authorizes and settles charges. It is the orchestration seam between
// pricing, the processor adapter, the repository, and event publishing.
type Service struct {
	repo      Repository
	pricer    *pricing.Pricer
	proc      processor.Processor
	publisher events.Publisher
	dir       *directory.Directory
	now       func() time.Time
}

// NewService wires a charge service. now may be nil, in which case time.Now
// (UTC) is used; tests can inject a fixed clock.
func NewService(
	repo Repository,
	pricer *pricing.Pricer,
	proc processor.Processor,
	publisher events.Publisher,
	dir *directory.Directory,
	now func() time.Time,
) *Service {
	if now == nil {
		now = func() time.Time { return time.Now().UTC() }
	}
	return &Service{repo: repo, pricer: pricer, proc: proc, publisher: publisher, dir: dir, now: now}
}

// Create runs the full charge flow:
//
//  1. validate the seller (exists, on platform, verified, currency matches),
//  2. compute platform_fee and processor_fee via pricing,
//  3. call the processor to authorize+capture,
//  4. persist the charge and emit payment.authorized then payment.settled.
//
// Idempotency is enforced one layer up (the API handler consults the
// idempotency store before calling this method), matching SPEC's rule that the
// Idempotency-Key is checked before any processor call.
func (s *Service) Create(ctx context.Context, in CreateInput) (Charge, error) {
	seller, err := s.dir.SellerOnPlatform(in.PlatformID, in.SellerID)
	if err != nil {
		return Charge{}, err
	}
	if seller.KYCStatus != directory.KYCVerified {
		return Charge{}, ErrSellerNotVerified
	}
	if in.Amount.Currency != seller.PayoutCurrency {
		return Charge{}, fmt.Errorf("%w: charge %s vs payout %s",
			ErrCurrencyMismatch, in.Amount.Currency, seller.PayoutCurrency)
	}

	// Fee computation — the ground-truth pricing package.
	quote, err := s.pricer.Quote(in.Amount, in.PlatformFeeBpsOverride)
	if err != nil {
		return Charge{}, err
	}

	chargeID := ids.Charge()

	// Processor call (authorize + capture in one step for this flow).
	res, err := s.proc.Charge(ctx, processor.ChargeRequest{
		ChargeID:   chargeID,
		Amount:     in.Amount,
		CardToken:  in.CardToken,
		Descriptor: in.Descriptor,
	})
	if err != nil {
		if errors.Is(err, processor.ErrDeclined) {
			// Persist the failed charge for auditability, then report decline.
			failed := s.buildCharge(chargeID, in, quote, "", StatusFailed)
			_ = s.repo.Create(ctx, failed)
			return failed, ErrDeclined
		}
		return Charge{}, fmt.Errorf("charges: processor error: %w", err)
	}

	charge := s.buildCharge(chargeID, in, quote, res.ProcessorRef, StatusSettled)
	if err := s.repo.Create(ctx, charge); err != nil {
		return Charge{}, err
	}

	// Emit events in causal order: authorized then settled. The ledger posts
	// the settlement entry off payment.settled.
	if err := s.emitAuthorizedAndSettled(ctx, charge); err != nil {
		// The charge succeeded at the processor; an event failure is logged by
		// the publisher and surfaced so the caller can trigger redelivery, but
		// we do not roll back the money movement.
		return charge, fmt.Errorf("charges: event publish failed: %w", err)
	}

	return charge, nil
}

func (s *Service) buildCharge(id string, in CreateInput, q pricing.Quote, ref string, status Status) Charge {
	zero, _ := money.Zero(in.Amount.Currency)
	return Charge{
		ID:             id,
		PlatformID:     in.PlatformID,
		SellerID:       in.SellerID,
		Amount:         in.Amount,
		PlatformFee:    q.PlatformFee,
		ProcessorFee:   q.ProcessorFee,
		Status:         status,
		IdempotencyKey: in.IdempotencyKey,
		ProcessorRef:   ref,
		CreatedAt:      s.now(),
		AmountRefunded: zero,
	}
}

func (s *Service) emitAuthorizedAndSettled(ctx context.Context, c Charge) error {
	data := events.PaymentData{
		ChargeID:     c.ID,
		PlatformID:   c.PlatformID,
		SellerID:     c.SellerID,
		Amount:       c.Amount,
		PlatformFee:  c.PlatformFee,
		ProcessorFee: c.ProcessorFee,
	}

	authorized, err := events.PaymentAuthorized(data)
	if err != nil {
		return err
	}
	if err := s.publisher.Publish(ctx, authorized); err != nil {
		return err
	}

	settled, err := events.PaymentSettled(data)
	if err != nil {
		return err
	}
	return s.publisher.Publish(ctx, settled)
}

// Get returns a charge by id.
func (s *Service) Get(ctx context.Context, id string) (Charge, error) {
	return s.repo.Get(ctx, id)
}
