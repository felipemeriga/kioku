// Package apierror defines the gateway's typed API errors and their JSON
// representation. Every error the public API returns is one of these, giving
// clients a stable machine-readable `code` plus a human-readable `message`.
package apierror

import (
	"encoding/json"
	"net/http"
)

// Code is a stable, machine-readable error identifier.
type Code string

const (
	CodeInvalidRequest   Code = "invalid_request"
	CodeUnauthorized     Code = "unauthorized"
	CodeNotFound         Code = "not_found"
	CodeConflict         Code = "conflict"
	CodeIdempotencyReuse Code = "idempotency_key_reuse"
	CodePaymentDeclined  Code = "payment_declined"
	CodeUnprocessable    Code = "unprocessable_entity"
	CodeInternal         Code = "internal_error"
	CodeUpstreamFailure  Code = "upstream_failure"
)

// Error is a typed API error carrying an HTTP status, a stable code, and a
// message. It implements the error interface so it can flow through services.
type Error struct {
	Status  int    `json:"-"`
	Code    Code   `json:"code"`
	Message string `json:"message"`
	// Details optionally carries field-level validation info.
	Details map[string]string `json:"details,omitempty"`
}

func (e *Error) Error() string { return string(e.Code) + ": " + e.Message }

// New builds an Error.
func New(status int, code Code, message string) *Error {
	return &Error{Status: status, Code: code, Message: message}
}

// WithDetails attaches field-level details and returns the same error.
func (e *Error) WithDetails(details map[string]string) *Error {
	e.Details = details
	return e
}

// Common constructors used across handlers.

func InvalidRequest(msg string) *Error {
	return New(http.StatusBadRequest, CodeInvalidRequest, msg)
}

func Unauthorized(msg string) *Error {
	return New(http.StatusUnauthorized, CodeUnauthorized, msg)
}

func NotFound(msg string) *Error {
	return New(http.StatusNotFound, CodeNotFound, msg)
}

func Conflict(msg string) *Error {
	return New(http.StatusConflict, CodeConflict, msg)
}

func IdempotencyReuse(msg string) *Error {
	return New(http.StatusUnprocessableEntity, CodeIdempotencyReuse, msg)
}

func PaymentDeclined(msg string) *Error {
	return New(http.StatusPaymentRequired, CodePaymentDeclined, msg)
}

func Unprocessable(msg string) *Error {
	return New(http.StatusUnprocessableEntity, CodeUnprocessable, msg)
}

func Internal(msg string) *Error {
	return New(http.StatusInternalServerError, CodeInternal, msg)
}

func Upstream(msg string) *Error {
	return New(http.StatusBadGateway, CodeUpstreamFailure, msg)
}

// envelope is the wire shape: { "error": { code, message, details } }.
type envelope struct {
	Error *Error `json:"error"`
}

// Write serializes err as a JSON error response with the appropriate status.
// If err is not an *Error, it is wrapped as an internal error so the client
// never sees a raw Go error string.
func Write(w http.ResponseWriter, err error) {
	apiErr, ok := err.(*Error)
	if !ok || apiErr == nil {
		apiErr = Internal("an unexpected error occurred")
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(apiErr.Status)
	_ = json.NewEncoder(w).Encode(envelope{Error: apiErr})
}
