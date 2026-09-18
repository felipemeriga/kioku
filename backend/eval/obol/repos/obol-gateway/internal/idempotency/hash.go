package idempotency

import (
	"crypto/sha256"
	"encoding/hex"
)

// RequestHash returns a stable fingerprint of a request body, used to detect
// when an Idempotency-Key is reused with a different payload.
func RequestHash(body []byte) string {
	sum := sha256.Sum256(body)
	return hex.EncodeToString(sum[:])
}
