// Package ids generates the prefixed snake-case identifiers used throughout
// Obol (chg_, rfnd_, pyt_, evt_, ...). See SPEC.md > Conventions.
package ids

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
)

// Prefixes for each entity kind, matching SPEC.md.
const (
	PrefixCharge   = "chg"
	PrefixRefund   = "rfnd"
	PrefixPayout   = "pyt"
	PrefixSeller   = "sell"
	PrefixPlatform = "plat"
	PrefixEvent    = "evt"
	PrefixAccount  = "acct"
	PrefixJournal  = "jrnl"
)

// Generator produces prefixed ids. The default Generator uses crypto/rand; a
// deterministic Generator can be injected in tests for reproducible ids.
type Generator interface {
	New(prefix string) string
}

// randGenerator is the production generator: <prefix>_<16 hex chars>.
type randGenerator struct{}

// NewGenerator returns the default random id generator.
func NewGenerator() Generator { return randGenerator{} }

func (randGenerator) New(prefix string) string {
	b := make([]byte, 8)
	if _, err := rand.Read(b); err != nil {
		// crypto/rand should never fail; panic is acceptable at process level.
		panic(fmt.Sprintf("ids: rand.Read failed: %v", err))
	}
	return prefix + "_" + hex.EncodeToString(b)
}

// Convenience helpers using the default generator.

var defaultGen = NewGenerator()

// Charge returns a new charge id, e.g. "chg_1a2b3c4d5e6f7081".
func Charge() string { return defaultGen.New(PrefixCharge) }

// Refund returns a new refund id.
func Refund() string { return defaultGen.New(PrefixRefund) }

// Payout returns a new payout batch id.
func Payout() string { return defaultGen.New(PrefixPayout) }

// Event returns a new event id.
func Event() string { return defaultGen.New(PrefixEvent) }
