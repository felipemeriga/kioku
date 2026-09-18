package api

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"

	"github.com/obol/obol-gateway/internal/apierror"
)

// maxBodyBytes caps request bodies to protect the server from oversized input.
const maxBodyBytes = 1 << 20 // 1 MiB

// writeJSON serializes v as a JSON response with the given status code.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if v != nil {
		_ = json.NewEncoder(w).Encode(v)
	}
}

// decodeJSON reads and strictly decodes the request body into v. It rejects
// unknown fields and bodies over the size cap, returning an *apierror.Error on
// failure so handlers can pass it straight to apierror.Write.
func decodeJSON(w http.ResponseWriter, r *http.Request, v any) ([]byte, error) {
	limited := http.MaxBytesReader(w, r.Body, maxBodyBytes)
	raw, err := io.ReadAll(limited)
	if err != nil {
		return nil, apierror.InvalidRequest("request body too large or unreadable")
	}
	if len(raw) == 0 {
		return nil, apierror.InvalidRequest("request body is required")
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.DisallowUnknownFields()
	if err := dec.Decode(v); err != nil {
		return raw, apierror.InvalidRequest("malformed JSON: " + err.Error())
	}
	return raw, nil
}
