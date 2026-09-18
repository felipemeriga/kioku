package api

import (
	"log/slog"
	"net/http"

	"github.com/obol/obol-gateway/internal/apierror"
	"github.com/obol/obol-gateway/internal/charges"
	"github.com/obol/obol-gateway/internal/idempotency"
	"github.com/obol/obol-gateway/internal/payouts"
	"github.com/obol/obol-gateway/internal/refunds"
)

// Deps is the set of dependencies the HTTP layer needs. main constructs the
// concrete services and passes them in, keeping the api package decoupled from
// wiring concerns.
type Deps struct {
	ChargeService *charges.Service
	ChargeRepo    charges.Repository
	RefundService *refunds.Service
	PayoutService *payouts.Service
	Idempotency   idempotency.Store
	Authenticator Authenticator
	Logger        *slog.Logger
}

// NewRouter builds the fully-wired HTTP handler for the gateway, including the
// middleware stack (request id -> logging -> recover -> auth) and every route.
func NewRouter(d Deps) http.Handler {
	logger := d.Logger
	if logger == nil {
		logger = slog.Default()
	}

	chg := newChargesHandler(d.ChargeService, d.Idempotency)
	rfnd := newRefundsHandler(d.RefundService, d.ChargeRepo)
	pyt := newPayoutsHandler(d.PayoutService)

	mux := http.NewServeMux()

	// Health (unauthenticated; auth middleware short-circuits /healthz).
	mux.HandleFunc("GET /healthz", health)

	// Charges.
	mux.HandleFunc("POST /v1/charges", chg.create)
	mux.HandleFunc("GET /v1/charges/{id}", chg.get)

	// Refunds — nested under a charge, plus a direct fetch by refund id.
	mux.HandleFunc("POST /v1/charges/{id}/refunds", rfnd.create)
	mux.HandleFunc("GET /v1/refunds/{id}", rfnd.get)

	// Payouts.
	mux.HandleFunc("POST /v1/payouts", pyt.create)
	mux.HandleFunc("GET /v1/payouts/{id}", pyt.get)

	// Fallback for unknown routes -> JSON 404.
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		apierror.Write(w, apierror.NotFound("no such endpoint: "+r.Method+" "+r.URL.Path))
	})

	return Chain(mux,
		RequestIDMiddleware(),
		Logging(logger),
		Recoverer(logger),
		APIKeyAuth(d.Authenticator),
	)
}
