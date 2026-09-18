// Package config loads gateway configuration from the environment. All values
// have sensible development defaults so the service boots with zero config, but
// production deployments should set them explicitly.
package config

import (
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config is the fully-resolved runtime configuration for the gateway.
type Config struct {
	// HTTP server.
	Addr            string        // listen address, e.g. ":8080"
	ReadTimeout     time.Duration // per-request read timeout
	WriteTimeout    time.Duration // per-request write timeout
	ShutdownTimeout time.Duration // graceful shutdown grace period

	// Auth. APIKeys is the set of accepted platform API keys. In this mock we
	// map each key to a platform id (Authorization: Bearer <key>).
	APIKeys map[string]string // key -> platform_id

	// LedgerURL is the base URL of the obol-ledger service that consumes the
	// events this gateway publishes (POST {LedgerURL}/internal/events).
	LedgerURL string

	// ProcessorFeeBps and ProcessorFeeFixedMinor model the mock card
	// processor's own fee: fee = round_half_even(amount*bps/10000) + fixed.
	ProcessorFeeBps        int64
	ProcessorFeeFixedMinor int64

	// DefaultPlatformFeeBps is used when a platform has no override configured.
	DefaultPlatformFeeBps int64

	// Env is a free-form environment label (development|staging|production).
	Env string
}

// Load reads configuration from the process environment, applying defaults.
func Load() (Config, error) {
	cfg := Config{
		Addr:                   getStr("GATEWAY_ADDR", ":8080"),
		ReadTimeout:            getDur("GATEWAY_READ_TIMEOUT", 15*time.Second),
		WriteTimeout:           getDur("GATEWAY_WRITE_TIMEOUT", 15*time.Second),
		ShutdownTimeout:        getDur("GATEWAY_SHUTDOWN_TIMEOUT", 20*time.Second),
		LedgerURL:              getStr("GATEWAY_LEDGER_URL", "http://obol-ledger:8000"),
		ProcessorFeeBps:        getInt("GATEWAY_PROCESSOR_FEE_BPS", 150),
		ProcessorFeeFixedMinor: getInt("GATEWAY_PROCESSOR_FEE_FIXED_MINOR", 25),
		DefaultPlatformFeeBps:  getInt("GATEWAY_DEFAULT_PLATFORM_FEE_BPS", 290),
		Env:                    getStr("GATEWAY_ENV", "development"),
	}

	cfg.APIKeys = parseAPIKeys(getStr(
		"GATEWAY_API_KEYS",
		// dev default: the sample platform from SPEC.md.
		"sk_test_marisqueira=plat_marisqueira",
	))
	if len(cfg.APIKeys) == 0 {
		return Config{}, fmt.Errorf("config: no API keys configured (set GATEWAY_API_KEYS)")
	}

	if cfg.DefaultPlatformFeeBps < 0 {
		return Config{}, fmt.Errorf("config: GATEWAY_DEFAULT_PLATFORM_FEE_BPS must be >= 0")
	}

	return cfg, nil
}

// parseAPIKeys parses a comma-separated list of key=platform_id pairs.
func parseAPIKeys(raw string) map[string]string {
	out := make(map[string]string)
	for _, pair := range strings.Split(raw, ",") {
		pair = strings.TrimSpace(pair)
		if pair == "" {
			continue
		}
		k, v, ok := strings.Cut(pair, "=")
		k, v = strings.TrimSpace(k), strings.TrimSpace(v)
		if !ok || k == "" || v == "" {
			continue
		}
		out[k] = v
	}
	return out
}

func getStr(key, def string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return def
}

func getInt(key string, def int64) int64 {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		if n, err := strconv.ParseInt(v, 10, 64); err == nil {
			return n
		}
	}
	return def
}

func getDur(key string, def time.Duration) time.Duration {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}
