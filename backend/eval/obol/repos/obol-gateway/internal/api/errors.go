package api

import (
	"errors"

	"github.com/obol/obol-gateway/internal/apierror"
	"github.com/obol/obol-gateway/internal/charges"
	"github.com/obol/obol-gateway/internal/directory"
	"github.com/obol/obol-gateway/internal/idempotency"
	"github.com/obol/obol-gateway/internal/payouts"
	"github.com/obol/obol-gateway/internal/refunds"
)

// mapError translates a domain/service error into a typed *apierror.Error with
// the correct HTTP status. Anything unrecognized becomes a 500. Keeping this
// mapping in one place means handlers stay thin.
func mapError(err error) *apierror.Error {
	if err == nil {
		return nil
	}

	// Already a typed API error? Pass it through.
	var apiErr *apierror.Error
	if errors.As(err, &apiErr) {
		return apiErr
	}

	switch {
	// Not-found cases.
	case errors.Is(err, charges.ErrNotFound),
		errors.Is(err, refunds.ErrNotFound),
		errors.Is(err, payouts.ErrNotFound),
		errors.Is(err, directory.ErrSellerNotFound),
		errors.Is(err, directory.ErrPlatformNotFound):
		return apierror.NotFound(err.Error())

	// Declines from the processor.
	case errors.Is(err, charges.ErrDeclined),
		errors.Is(err, payouts.ErrDeclined):
		return apierror.PaymentDeclined(err.Error())

	// Idempotency conflicts.
	case errors.Is(err, idempotency.ErrKeyInFlight):
		return apierror.Conflict("a request with this Idempotency-Key is already in progress")
	case errors.Is(err, idempotency.ErrRequestMismatch):
		return apierror.IdempotencyReuse("Idempotency-Key was reused with a different request payload")

	// Business-rule violations -> 422 Unprocessable Entity.
	case errors.Is(err, charges.ErrSellerNotVerified),
		errors.Is(err, charges.ErrCurrencyMismatch),
		errors.Is(err, refunds.ErrChargeNotSettled),
		errors.Is(err, refunds.ErrExceedsRefundable),
		errors.Is(err, refunds.ErrCurrencyMismatch),
		errors.Is(err, payouts.ErrCurrencyMismatch),
		errors.Is(err, payouts.ErrSellerNotVerified),
		errors.Is(err, directory.ErrSellerNotOnPlatform):
		return apierror.Unprocessable(err.Error())

	// Upstream (processor / event publish) failures.
	case errors.Is(err, refunds.ErrProcessorFailed):
		return apierror.Upstream(err.Error())

	default:
		return apierror.Internal("an unexpected error occurred")
	}
}
