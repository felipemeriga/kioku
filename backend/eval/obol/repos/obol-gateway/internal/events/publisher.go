package events

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"
)

// Publisher delivers event envelopes to downstream consumers (the ledger).
type Publisher interface {
	Publish(ctx context.Context, env Envelope) error
}

// HTTPPublisher POSTs event envelopes to the ledger's /internal/events
// endpoint. The ledger consumes the envelope and posts the corresponding
// journal entries. It is idempotent on event.id, so retries here are safe.
type HTTPPublisher struct {
	baseURL string
	client  *http.Client
	logger  *slog.Logger
}

// NewHTTPPublisher constructs an HTTPPublisher targeting the given ledger base
// URL (e.g. "http://obol-ledger:8000").
func NewHTTPPublisher(baseURL string, client *http.Client, logger *slog.Logger) *HTTPPublisher {
	if client == nil {
		client = &http.Client{Timeout: 10 * time.Second}
	}
	if logger == nil {
		logger = slog.Default()
	}
	return &HTTPPublisher{baseURL: baseURL, client: client, logger: logger}
}

// Publish sends the envelope to {baseURL}/internal/events. A non-2xx response
// is treated as a delivery failure so the caller can retry.
func (p *HTTPPublisher) Publish(ctx context.Context, env Envelope) error {
	body, err := json.Marshal(env)
	if err != nil {
		return fmt.Errorf("events: marshal envelope: %w", err)
	}

	url := p.baseURL + "/internal/events"
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("events: build request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Obol-Event-Id", env.ID)
	req.Header.Set("X-Obol-Event-Type", string(env.Type))

	resp, err := p.client.Do(req)
	if err != nil {
		return fmt.Errorf("events: deliver %s: %w", env.Type, err)
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<16))

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("events: ledger rejected %s (%s): status %d", env.Type, env.ID, resp.StatusCode)
	}

	p.logger.Info("event published",
		slog.String("event_id", env.ID),
		slog.String("event_type", string(env.Type)),
	)
	return nil
}

// Ensure HTTPPublisher satisfies Publisher.
var _ Publisher = (*HTTPPublisher)(nil)
