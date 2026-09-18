// Command gateway is the Obol payment API edge. It wires configuration, the
// domain services (charges, refunds, payouts), the mock processor adapter, the
// idempotency store, the pricing engine, and the event publisher, then serves
// the public REST API over HTTP with graceful shutdown.
package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/obol/obol-gateway/internal/api"
	"github.com/obol/obol-gateway/internal/charges"
	"github.com/obol/obol-gateway/internal/config"
	"github.com/obol/obol-gateway/internal/directory"
	"github.com/obol/obol-gateway/internal/events"
	"github.com/obol/obol-gateway/internal/idempotency"
	"github.com/obol/obol-gateway/internal/payouts"
	"github.com/obol/obol-gateway/internal/pricing"
	"github.com/obol/obol-gateway/internal/processor"
	"github.com/obol/obol-gateway/internal/refunds"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	if err := run(logger); err != nil {
		logger.Error("gateway exited with error", slog.Any("error", err))
		os.Exit(1)
	}
}

func run(logger *slog.Logger) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	logger.Info("configuration loaded",
		slog.String("env", cfg.Env),
		slog.String("addr", cfg.Addr),
		slog.String("ledger_url", cfg.LedgerURL),
		slog.Int64("default_platform_fee_bps", cfg.DefaultPlatformFeeBps),
	)

	// Fee/pricing engine (ground-truth fee computation).
	pricer, err := pricing.NewPricer(cfg.DefaultPlatformFeeBps, pricing.ProcessorFeeSchedule{
		Bps:        cfg.ProcessorFeeBps,
		FixedMinor: cfg.ProcessorFeeFixedMinor,
	})
	if err != nil {
		return err
	}

	// Mock card processor.
	proc := processor.NewMock()

	// Event publisher -> ledger /internal/events.
	publisher := events.NewHTTPPublisher(cfg.LedgerURL, &http.Client{Timeout: 10 * time.Second}, logger)

	// Merchant directory seeded with SPEC sample data.
	dir := directory.NewSeeded()

	// Repositories (in-memory for this build).
	chargeRepo := charges.NewMemoryRepository()
	refundRepo := refunds.NewMemoryRepository()
	payoutRepo := payouts.NewMemoryRepository()

	// Services.
	chargeSvc := charges.NewService(chargeRepo, pricer, proc, publisher, dir, nil)
	refundSvc := refunds.NewService(refundRepo, chargeRepo, proc, publisher, nil)
	payoutSvc := payouts.NewService(payoutRepo, proc, publisher, dir, nil)

	// HTTP router.
	handler := api.NewRouter(api.Deps{
		ChargeService: chargeSvc,
		ChargeRepo:    chargeRepo,
		RefundService: refundSvc,
		PayoutService: payoutSvc,
		Idempotency:   idempotency.NewMemoryStore(),
		Authenticator: api.NewKeyring(cfg.APIKeys),
		Logger:        logger,
	})

	srv := &http.Server{
		Addr:         cfg.Addr,
		Handler:      handler,
		ReadTimeout:  cfg.ReadTimeout,
		WriteTimeout: cfg.WriteTimeout,
	}

	// Start the server and wait for a shutdown signal.
	serveErr := make(chan error, 1)
	go func() {
		logger.Info("gateway listening", slog.String("addr", cfg.Addr))
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			serveErr <- err
		}
	}()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	select {
	case err := <-serveErr:
		return err
	case <-ctx.Done():
		logger.Info("shutdown signal received; draining connections")
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return err
	}
	logger.Info("gateway stopped cleanly")
	return nil
}
