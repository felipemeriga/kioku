# obol-gateway

The **payment API edge** for Obol — embedded money-movement infrastructure for
online marketplaces. `obol-gateway` is the public REST API that owns charges,
refunds, payouts, idempotency, the (mock) card-processor adapter, fee/pricing
computation, and event publishing.

It **never does accounting itself**. It moves money via the processor and emits
events; the [`obol-ledger`](../obol-ledger) consumes those events and posts the
double-entry journal entries. The merchant dashboard
[`obol-console`](../obol-console) reads projections from both services and
triggers refunds through this gateway.

- Language: Go 1.22
- Module: `github.com/obol/obol-gateway`
- No third-party dependencies — standard library only.

## Where Obol fits

```
buyer ──pays──▶  obol-console (merchant UI)
                      │  BFF proxy
                      ▼
                obol-gateway  ──emits events──▶  obol-ledger
                 (this repo)                     (double-entry)
                      │
                      ▼
              mock card processor
```

## Money

Money is always an integer amount in **minor units** plus an ISO-4217 currency —
never a float. Arithmetic is only allowed between same-currency values.

```json
{ "amount_minor": 4999, "currency": "USD" }   // = $49.99
```

The platform fee is computed with **banker's rounding** (round half to even):

```
platform_fee = round_half_even(charge_amount * platform_fee_bps / 10000)
```

Basis points: 1 bps = 0.01%, so a 2.9% fee is `290` bps. See
[`internal/money`](internal/money) for the `Money` type and the exact rounding
helper, and [`internal/pricing`](internal/pricing) for fee computation.

## Endpoints

| Method | Path                         | Description                              |
| ------ | ---------------------------- | ---------------------------------------- |
| POST   | `/v1/charges`                | Authorize + settle a charge (idempotent) |
| GET    | `/v1/charges/{id}`           | Fetch a charge                           |
| POST   | `/v1/charges/{id}/refunds`   | Refund all or part of a charge           |
| GET    | `/v1/refunds/{id}`           | Fetch a refund                           |
| POST   | `/v1/payouts`                | Execute a seller payout                  |
| GET    | `/v1/payouts/{id}`           | Fetch a payout batch                     |
| GET    | `/healthz`                   | Health probe (unauthenticated)           |

Authentication is `Authorization: Bearer <api_key>`; each key maps to a platform
id, and every resource is scoped to the authenticated platform.

A full sketch of the API lives in [`openapi.yaml`](openapi.yaml).

## The three key flows

### 1. Fee computation (charge flow)

`POST /v1/charges` → `charges.Service.Create`:

1. validate the seller (exists, on-platform, KYC-verified, currency matches),
2. compute `platform_fee` and `processor_fee` via **`internal/pricing`**,
3. call **`internal/processor`** to authorize + capture,
4. persist the charge and publish `payment.authorized` then `payment.settled`.

For the canonical sample charge `chg_0001` (€120.00 at 290 bps):

```
amount        = { 12000, "EUR" }
platform_fee  = round_half_even(12000 * 290 / 10000) = { 348,   "EUR" }   (€3.48)
processor_fee = round_half_even(12000 * 150 / 10000) + 25 = { 205, "EUR" }
seller_net    = 12000 - 348 - 205 = { 11447, "EUR" }                       (€114.47)
```

The ledger later **records** that same `platform_fee` to `platform_revenue`
(gateway computes, ledger records — SPEC cross-repo relationship #2).

### 2. Idempotency

Every `POST /v1/charges` must carry an `Idempotency-Key` header. The key is
checked in **`internal/idempotency`** *before any processor call*:

- first request → the key is reserved, the charge runs, and the response is
  stored under the key;
- a retry with the same key **and** the same body → the stored response is
  replayed verbatim (`Idempotent-Replayed: true`), so the buyer is never
  double-charged;
- the same key with a *different* body → `422 idempotency_key_reuse`;
- a concurrent duplicate still in flight → `409 conflict`.

Keys are scoped per platform so they never collide across tenants.

### 3. Refunds (spans all three repos)

```
console RefundButton → BFF /refunds → gateway POST /v1/charges/{id}/refunds
      → processor.Refund → publish refund.completed → ledger posts reversal
```

The gateway half lives in **`internal/refunds`**: `refunds.Service.Create`
validates the charge is settled and within its remaining refundable balance,
calls `processor.Refund` against the original `processor_ref`, advances the
charge to `partially_refunded`/`refunded`, and publishes `refund.completed`. The
ledger consumes that event and posts the mirror-image reversal entry (debits
`seller_payable` + `platform_revenue`, credits `processor_clearing`).

### Payouts (ledger → gateway)

The ledger builds a payout batch from a seller's `seller_payable` balance and
calls `POST /v1/payouts`. The gateway calls `processor.Payout`, then emits
`payout.scheduled` and `payout.paid`; the ledger marks the batch paid and debits
`seller_payable` (SPEC cross-repo relationship #4).

## Events published

All events share the envelope `{ id, type, ts, data }`, are delivered by POST to
`{LEDGER_URL}/internal/events`, and are idempotent on `event.id`.

| Type                 | Emitted by            | Ledger effect                              |
| -------------------- | --------------------- | ------------------------------------------ |
| `payment.authorized` | charge service        | (informational)                            |
| `payment.settled`    | charge service        | posts the settlement journal entry         |
| `refund.completed`   | refund service        | posts the reversal journal entry           |
| `payout.scheduled`   | payout service        | (informational)                            |
| `payout.paid`        | payout service        | marks batch paid, debits `seller_payable`  |

## Project layout

```
cmd/gateway/           main: config + wiring + HTTP server (graceful shutdown)
internal/config/       env-driven configuration
internal/money/        Money type, same-currency arithmetic, banker's rounding
internal/pricing/      fee/pricing computation (ground truth)
internal/idempotency/  Idempotency-Key store (ground truth)
internal/processor/    deterministic mock card-processor adapter (ground truth)
internal/charges/      charge model + repository + authorize/settle service
internal/refunds/      refund model + repository + service (emits refund.completed)
internal/payouts/      payout batch model + repository + execution service
internal/events/       event envelope, constructors, HTTP + in-memory publishers
internal/directory/    platforms & sellers, seeded with SPEC sample data
internal/ids/          prefixed id generation (chg_, rfnd_, pyt_, evt_, ...)
internal/apierror/     typed API errors + JSON error responses
internal/api/          router, middleware, one handler file per resource
```

## Running

```bash
make run          # start on :8080 with development defaults
make test         # run the test suite
make test-race    # with the race detector
make build        # compile ./bin/gateway
make docker       # build the container image
```

### Configuration

| Env var                            | Default                              | Meaning                              |
| ---------------------------------- | ------------------------------------ | ------------------------------------ |
| `GATEWAY_ADDR`                     | `:8080`                              | listen address                       |
| `GATEWAY_LEDGER_URL`               | `http://obol-ledger:8000`            | where events are POSTed              |
| `GATEWAY_API_KEYS`                 | `sk_test_marisqueira=plat_marisqueira` | `key=platform_id` pairs (CSV)      |
| `GATEWAY_DEFAULT_PLATFORM_FEE_BPS` | `290`                                | default platform fee (2.9%)          |
| `GATEWAY_PROCESSOR_FEE_BPS`        | `150`                                | processor fee rate (1.5%)            |
| `GATEWAY_PROCESSOR_FEE_FIXED_MINOR`| `25`                                 | fixed processor fee (€0.25)          |

### Example: create the sample charge

```bash
curl -sX POST http://localhost:8080/v1/charges \
  -H "Authorization: Bearer sk_test_marisqueira" \
  -H "Idempotency-Key: idem-chg-0001" \
  -H "Content-Type: application/json" \
  -d '{
        "seller_id": "sell_atelier",
        "amount": { "amount_minor": 12000, "currency": "EUR" },
        "card_token": "tok_visa"
      }'
```

## Fixed sample data

Seeded in [`internal/directory`](internal/directory) so examples line up across
all three repos:

- Platform `plat_marisqueira` — "Marisqueira Marketplace", country `PT`,
  `default_platform_fee_bps = 290`.
- Sellers `sell_atelier` ("Atelier Costa", verified, EUR) and `sell_ceramica`
  ("Cerâmica do Vale", verified, EUR).
- Sample charge `chg_0001`: amount €120.00, platform_fee €3.48, processor_fee
  €2.05, seller net €114.47.
