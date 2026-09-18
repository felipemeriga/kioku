package api

import (
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/obol/obol-gateway/internal/apierror"
	"github.com/obol/obol-gateway/internal/ids"
)

// Middleware is the standard http middleware signature.
type Middleware func(http.Handler) http.Handler

// Chain applies middlewares in order, so Chain(h, a, b) runs a then b then h.
func Chain(h http.Handler, mws ...Middleware) http.Handler {
	for i := len(mws) - 1; i >= 0; i-- {
		h = mws[i](h)
	}
	return h
}

// RequestIDMiddleware assigns each request an id (honoring an inbound
// X-Request-Id if present) and echoes it back in the response header and
// request context. The accessor RequestID(ctx) reads the value back out.
func RequestIDMiddleware() Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			rid := r.Header.Get("X-Request-Id")
			if rid == "" {
				rid = "req_" + strings.TrimPrefix(ids.Event(), "evt_")
			}
			w.Header().Set("X-Request-Id", rid)
			r = r.WithContext(withRequestID(r.Context(), rid))
			next.ServeHTTP(w, r)
		})
	}
}

// statusRecorder captures the response status for logging.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (s *statusRecorder) WriteHeader(code int) {
	s.status = code
	s.ResponseWriter.WriteHeader(code)
}

// Logging logs one structured line per request with method, path, status, and
// latency, tagged with the request id.
func Logging(logger *slog.Logger) Middleware {
	if logger == nil {
		logger = slog.Default()
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()
			rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}
			next.ServeHTTP(rec, r)
			logger.Info("request",
				slog.String("request_id", RequestID(r.Context())),
				slog.String("method", r.Method),
				slog.String("path", r.URL.Path),
				slog.Int("status", rec.status),
				slog.Duration("latency", time.Since(start)),
			)
		})
	}
}

// Authenticator resolves an API key to a platform id.
type Authenticator interface {
	PlatformForKey(key string) (platformID string, ok bool)
}

// APIKeyAuth authenticates requests via `Authorization: Bearer <api_key>`.
// This is a stub — a real gateway would verify signed keys — but it enforces
// tenant identity so every downstream call is scoped to a platform.
func APIKeyAuth(auth Authenticator) Middleware {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Health check is unauthenticated.
			if r.URL.Path == "/healthz" {
				next.ServeHTTP(w, r)
				return
			}

			header := r.Header.Get("Authorization")
			const prefix = "Bearer "
			if !strings.HasPrefix(header, prefix) {
				apierror.Write(w, apierror.Unauthorized("missing or malformed Authorization header"))
				return
			}
			key := strings.TrimSpace(strings.TrimPrefix(header, prefix))
			platformID, ok := auth.PlatformForKey(key)
			if !ok {
				apierror.Write(w, apierror.Unauthorized("invalid API key"))
				return
			}
			r = r.WithContext(withPlatformID(r.Context(), platformID))
			next.ServeHTTP(w, r)
		})
	}
}

// Recoverer converts a panic in a handler into a 500 JSON error instead of
// crashing the server.
func Recoverer(logger *slog.Logger) Middleware {
	if logger == nil {
		logger = slog.Default()
	}
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			defer func() {
				if rec := recover(); rec != nil {
					logger.Error("panic recovered",
						slog.String("request_id", RequestID(r.Context())),
						slog.Any("panic", rec),
					)
					apierror.Write(w, apierror.Internal("an unexpected error occurred"))
				}
			}()
			next.ServeHTTP(w, r)
		})
	}
}
