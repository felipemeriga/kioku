# Obol Gateway — Public API Reference

> The public REST API of **obol-gateway** (Go), the payment API edge. This is
> the API a platform's backend integrates. It derives from the canonical domain
> spec (`SPEC.md`). For how the gateway fits the system, see
> [02-system-architecture.md](./02-system-architecture.md); for terms, see
> [03-domain-glossary.md](./03-domain-glossary.md); for a guided end-to-end
> integration, see [11-integration-guide.md](./11-integration-guide.md).

All examples use Obol's fixed sample data so they line up across docs:

- Platform `plat_marisqueira` ("Marisqueira Marketplace", `PT`,
  `default_platform_fee_bps = 290`).
- Sellers `sell_atelier` ("Atelier Costa", EUR) and `sell_ceramica`
  ("Cerâmica do Vale", EUR).
- Charge `chg_0001` — `sell_atelier`, `{ 12000, "EUR" }`, platform_fee
  `{ 348, "EUR" }`, processor_fee `{ 205, "EUR" }`, seller net `{ 11447, "EUR" }`.

---

## Base URL and versioning

```
https://api.obol.example/v1
```

The API is versioned in the path (`/v1`). Breaking changes ship under a new
version prefix; additive changes (new fields, new endpoints) ship within `/v1`.

## Conventions

- **Transport:** HTTPS only. JSON request and response bodies
  (`Content-Type: application/json`).
- **Money:** every monetary value is a `Money` object
  `{ "amount_minor": <int>, "currency": "<ISO-4217>" }`. Never a float. See
  [03-domain-glossary.md](./03-domain-glossary.md#money).
- **IDs:** prefixed snake ids (`chg_`, `rfnd_`, `pyt_`, `sell_`, `plat_`,
  `evt_`).
- **Timestamps:** RFC-3339 UTC (e.g. `2026-09-18T10:15:30Z`).

---

## Authentication — API key

Every request must include a secret API key as a bearer token:

```
Authorization: Bearer sk_live_marisqueira_9f2b...
```

- Keys are issued per **platform**. A key authenticates as `plat_marisqueira`
  and scopes all requests to that platform's sellers and charges.
- Keys come in `sk_live_...` (production) and `sk_test_...` (sandbox) forms.
- Never send a key from a browser. The → Console's Express BFF holds the key
  server-side; the SPA never sees it.

A missing or invalid key returns `401 Unauthorized`. A key trying to act on
another platform's resource returns `403 Forbidden`.

---

## Idempotency — the `Idempotency-Key` header

Mutating requests that move money are **idempotent by key**. `POST /v1/charges`
**requires** an `Idempotency-Key` header; `POST .../refunds` and
`POST /v1/payouts` accept one and it is strongly recommended.

```
Idempotency-Key: 5c1e0f7a-2b44-4c9e-9d1a-8f0e2b3c4d5e
```

Semantics (implemented in the gateway `idempotency` package):

- The key is stored and checked **before any processor call**, so a retried
  request never double-charges.
- **Same key + same request body** → the original response is returned (the
  operation runs at most once). The resulting → Charge records the key as
  `idempotency_key`.
- **Same key + different body** → `409 Conflict` with error code
  `idempotency_key_reuse`.
- Keys are single-use per logical operation. Use a fresh UUID per operation;
  reuse the *same* key only when retrying the *same* operation.
- Recommended retention: keys are honored for at least 24 hours.

See [03-domain-glossary.md](./03-domain-glossary.md#idempotency).

---

## Pagination

List endpoints use cursor pagination:

- Request: `?limit=<1..100>` (default `25`) and `?starting_after=<id>`.
- Response envelope:

```json
{
  "object": "list",
  "data": [ /* ... */ ],
  "has_more": true,
  "next_cursor": "chg_0042"
}
```

Fetch the next page by passing `starting_after=<next_cursor>`. When `has_more`
is `false`, `next_cursor` is `null`.

---

## Errors

Errors use standard HTTP status codes and a consistent body:

```json
{
  "error": {
    "type": "invalid_request_error",
    "code": "missing_idempotency_key",
    "message": "POST /v1/charges requires an Idempotency-Key header.",
    "param": "Idempotency-Key"
  }
}
```

| HTTP | `type` | When |
|---|---|---|
| 400 | `invalid_request_error` | malformed body, missing/invalid field |
| 401 | `authentication_error` | missing or invalid API key |
| 403 | `permission_error` | key not authorized for the resource |
| 404 | `not_found_error` | unknown `chg_`/`sell_`/etc. id |
| 409 | `conflict_error` | idempotency key reuse with a different body |
| 422 | `processing_error` | processor declined / business rule failed |
| 429 | `rate_limit_error` | too many requests |
| 5xx | `api_error` | unexpected gateway/processor failure |

Common `code` values: `missing_idempotency_key`, `idempotency_key_reuse`,
`currency_mismatch`, `seller_not_verified`, `charge_not_settled`,
`refund_exceeds_charge`, `insufficient_balance`.

Money math rule reflected here: arithmetic is only allowed between same-currency
`Money`; a cross-currency request is rejected with `currency_mismatch`.

---

## Endpoints

### `POST /v1/charges`

Create a → Charge: authorize and settle a buyer payment, computing the fee
split. **Requires** an `Idempotency-Key` header.

The platform sends the seller and the gross amount. The gateway `pricing`
package computes `platform_fee` from the platform's `default_platform_fee_bps`
using banker's rounding; the processor determines `processor_fee`. The gateway
returns the full charge.

**Request**

```http
POST /v1/charges HTTP/1.1
Host: api.obol.example
Authorization: Bearer sk_live_marisqueira_9f2b...
Idempotency-Key: 5c1e0f7a-2b44-4c9e-9d1a-8f0e2b3c4d5e
Content-Type: application/json

{
  "seller_id": "sell_atelier",
  "amount": { "amount_minor": 12000, "currency": "EUR" },
  "payment_method": "tok_visa_4242"
}
```

**Response — `201 Created`**

```json
{
  "id": "chg_0001",
  "object": "charge",
  "platform_id": "plat_marisqueira",
  "seller_id": "sell_atelier",
  "amount":        { "amount_minor": 12000, "currency": "EUR" },
  "platform_fee":  { "amount_minor": 348,   "currency": "EUR" },
  "processor_fee": { "amount_minor": 205,   "currency": "EUR" },
  "seller_net":    { "amount_minor": 11447, "currency": "EUR" },
  "status": "settled",
  "idempotency_key": "5c1e0f7a-2b44-4c9e-9d1a-8f0e2b3c4d5e",
  "processor_ref": "mockproc_auth_7Ka9",
  "created_at": "2026-09-18T10:15:30Z"
}
```

Fee derivation for this response:
`platform_fee = round_half_even(12000 * 290 / 10000) = 348`;
`seller_net = 12000 − 348 − 205 = 11447`.

**Status codes**

| Code | Meaning |
|---|---|
| 201 | charge authorized and settled |
| 400 | missing `Idempotency-Key`, malformed body |
| 403 | key not authorized for `seller_id` |
| 409 | `Idempotency-Key` reused with a different body |
| 422 | processor declined, or `currency_mismatch` |

**Events emitted** (gateway → ledger; see
[03-domain-glossary.md](./03-domain-glossary.md#events)):

- `payment.authorized` — `{ charge_id, platform_id, seller_id, amount,
  platform_fee, processor_fee }` (recorded).
- `payment.settled` — same `data` → **ledger posts the settlement
  JournalEntry** (DEBIT `processor_clearing` 12000; CREDIT `platform_revenue`
  348; CREDIT `processor_fees` 205; CREDIT `seller_payable:sell_atelier`
  11447).

---

### `GET /v1/charges/{id}`

Retrieve a single → Charge by id.

**Request**

```http
GET /v1/charges/chg_0001 HTTP/1.1
Host: api.obol.example
Authorization: Bearer sk_live_marisqueira_9f2b...
```

**Response — `200 OK`**

```json
{
  "id": "chg_0001",
  "object": "charge",
  "platform_id": "plat_marisqueira",
  "seller_id": "sell_atelier",
  "amount":        { "amount_minor": 12000, "currency": "EUR" },
  "platform_fee":  { "amount_minor": 348,   "currency": "EUR" },
  "processor_fee": { "amount_minor": 205,   "currency": "EUR" },
  "seller_net":    { "amount_minor": 11447, "currency": "EUR" },
  "status": "settled",
  "idempotency_key": "5c1e0f7a-2b44-4c9e-9d1a-8f0e2b3c4d5e",
  "processor_ref": "mockproc_auth_7Ka9",
  "created_at": "2026-09-18T10:15:30Z"
}
```

If the charge has been refunded, `status` is `refunded` or
`partially_refunded`. See → Charge states in the glossary.

**Status codes**

| Code | Meaning |
|---|---|
| 200 | found |
| 404 | no charge with that id under this platform |

**Events emitted:** none (read-only).

---

### `POST /v1/charges/{id}/refunds`

Create a → Refund reversing all or part of a settled → Charge. Moves money back
to the buyer via the processor and triggers the ledger reversal. An
`Idempotency-Key` is recommended.

This is the endpoint the → Console's `RefundButton` reaches through the BFF's
`refunds` route — the refund flow spans console → gateway → ledger. See
[11-integration-guide.md](./11-integration-guide.md).

**Request — partial refund of €40.00**

```http
POST /v1/charges/chg_0001/refunds HTTP/1.1
Host: api.obol.example
Authorization: Bearer sk_live_marisqueira_9f2b...
Idempotency-Key: b7d2e1a0-3c55-4d6f-8e2b-1a0f9c8b7d6e
Content-Type: application/json

{
  "amount": { "amount_minor": 4000, "currency": "EUR" },
  "reason": "buyer_returned_item"
}
```

To refund the full charge, omit `amount` (the gateway defaults to the remaining
refundable amount) or pass the full `{ 12000, "EUR" }`.

**Response — `201 Created`**

```json
{
  "id": "rfnd_0001",
  "object": "refund",
  "charge_id": "chg_0001",
  "amount": { "amount_minor": 4000, "currency": "EUR" },
  "reason": "buyer_returned_item",
  "status": "completed",
  "created_at": "2026-09-18T14:02:11Z"
}
```

The parent charge transitions to `partially_refunded` (or `refunded` for a full
refund).

**Status codes**

| Code | Meaning |
|---|---|
| 201 | refund completed |
| 404 | unknown charge id |
| 422 | `charge_not_settled`, `refund_exceeds_charge`, or `currency_mismatch` |

**Events emitted:**

- `refund.completed` — `{ refund_id, charge_id, amount }` → **ledger posts the
  reversal entry** (mirror-image: debit `seller_payable:sell_atelier` and
  `platform_revenue`, credit `processor_clearing`, with proportional fee
  give-back). The original entry is never deleted.

---

### `POST /v1/payouts`

Execute a seller → Payout through the processor. This endpoint is normally
called by the **ledger's** `payouts` module when it builds and runs a →
PayoutBatch (`POST /v1/payout-batches` on the ledger builds the batch; that
module then calls this gateway endpoint to move the money). Documented here
because it is part of the gateway's surface.

The seller must be → KYC `verified`; otherwise `422 seller_not_verified`.

**Request**

```http
POST /v1/payouts HTTP/1.1
Host: api.obol.example
Authorization: Bearer sk_live_marisqueira_9f2b...
Idempotency-Key: e3f4a5b6-7c88-49da-9b0c-1d2e3f4a5b6c
Content-Type: application/json

{
  "batch_id": "pyt_0001",
  "seller_id": "sell_atelier",
  "amount": { "amount_minor": 11447, "currency": "EUR" }
}
```

**Response — `200 OK`**

```json
{
  "batch_id": "pyt_0001",
  "object": "payout",
  "seller_id": "sell_atelier",
  "amount": { "amount_minor": 11447, "currency": "EUR" },
  "status": "paid",
  "processor_ref": "mockproc_payout_Q3xL",
  "created_at": "2026-09-18T18:00:05Z"
}
```

**Status codes**

| Code | Meaning |
|---|---|
| 200 | payout paid |
| 404 | unknown seller/batch |
| 422 | `seller_not_verified`, `insufficient_balance`, or `currency_mismatch` |

**Events emitted:**

- `payout.scheduled` — `{ batch_id, seller_id, amount, scheduled_for }` (emitted
  when the batch is scheduled; recorded by the ledger).
- `payout.paid` — `{ batch_id, seller_id, amount, processor_ref }` → **ledger
  marks the batch `paid` and debits `seller_payable:sell_atelier`**, reducing
  what Obol owes the seller.

---

## Related ledger endpoints (not on the gateway)

Balances, statements, and payout-batch building live on **obol-ledger**, not the
gateway, but integrators need them:

- `GET  /v1/accounts/{account_id}/balance` — derived → balance.
- `GET  /v1/accounts/{account_id}/statement` — the account → statement.
- `POST /v1/payout-batches` — build a → PayoutBatch from a seller's
  `seller_payable` balance (then the ledger calls gateway `POST /v1/payouts`).
- `GET  /v1/payout-batches/{batch_id}` — retrieve a batch.
- `POST /internal/events` — internal event intake (gateway → ledger).

For an account id, the seller's payable account is
`seller_payable:sell_atelier`. See
[02-system-architecture.md](./02-system-architecture.md) and
[11-integration-guide.md](./11-integration-guide.md).

---

## Quick reference

| Method | Path | Purpose | Emits |
|---|---|---|---|
| POST | `/v1/charges` | create charge (auth + settle) | `payment.authorized`, `payment.settled` |
| GET | `/v1/charges/{id}` | retrieve charge | — |
| POST | `/v1/charges/{id}/refunds` | refund all/part of a charge | `refund.completed` |
| POST | `/v1/payouts` | execute a seller payout | `payout.scheduled`, `payout.paid` |
