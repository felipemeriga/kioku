package api

import "context"

// ctxKey is an unexported type for context keys defined in this package, to
// avoid collisions with keys from other packages.
type ctxKey int

const (
	ctxKeyRequestID ctxKey = iota
	ctxKeyPlatformID
)

// withRequestID returns a copy of ctx carrying the request id.
func withRequestID(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, ctxKeyRequestID, id)
}

// RequestID returns the request id stored in ctx, or "" if absent.
func RequestID(ctx context.Context) string {
	id, _ := ctx.Value(ctxKeyRequestID).(string)
	return id
}

// withPlatformID returns a copy of ctx carrying the authenticated platform id.
func withPlatformID(ctx context.Context, id string) context.Context {
	return context.WithValue(ctx, ctxKeyPlatformID, id)
}

// PlatformID returns the authenticated platform id stored in ctx, or "".
func PlatformID(ctx context.Context) string {
	id, _ := ctx.Value(ctxKeyPlatformID).(string)
	return id
}
