# Obol — Canonical Domain Spec (source of truth)

> This file is the ground truth every repo and doc must conform to. All three
> repos (`obol-gateway`, `obol-ledger`, `obol-console`) and all 12 docs derive
> their entities, field names, event schemas, and money-movement rules from
> here. If code and docs disagree, this file wins. It is NOT one of the 12
> published docs — it is the internal contract.

## The company

**Obol** is embedded money-movement infrastructure for online marketplaces.
A marketplace (the **platform**, Obol's direct customer) integrates Obol to:

- accept **buyer** payments for orders,
- split each payment into a **platform fee** and a **seller** share,
- hold seller funds as a balance,
- **pay out** sellers on a schedule,
- keep an auditable **double-entry ledger** of every cent.

Obol is a slice of "Stripe Connect"-style functionality, deliberately scoped
to charges, refunds, the ledger, and payouts.

## Money

Money is ALWAYS represented as integer minor units + an ISO-4217 currency.
Never floats. The canonical shape (same field names in every language):

```
Money { amount_minor: int64, currency: string }   # e.g. { 4999, "USD" } = $49.99
```

Rules:
- Arithmetic only between same-currency Money. Cross-currency is rejected.
- `platform_fee = round_half_even(charge_amount * platform_fee_bps / 10000)`.
- Basis points (`bps`): 1 bps = 0.01%. A 2.9% fee is `290` bps.

## Core entities (identical field names across repos)

- **Platform** — Obol's customer (the marketplace). `id, name, country,
  default_platform_fee_bps, created_at`.
- **Seller** — a sub-merchant selling on the platform. `id, platform_id,
  display_name, kyc_status (pending|verified|rejected), payout_currency,
  created_at`.
- **Charge** — a buyer payment. `id, platform_id, seller_id, amount (Money),
  platform_fee (Money), processor_fee (Money), status, idempotency_key,
  processor_ref, created_at`. Status: `pending → authorized → settled`, or
  `failed`, or `refunded` / `partially_refunded`.
- **Refund** — reverses all or part of a charge. `id, charge_id, amount
  (Money), reason, status (pending|completed|failed), created_at`.
- **PayoutBatch** — scheduled movement of a seller's balance to their bank.
  `id, seller_id, amount (Money), status (scheduled|processing|paid|failed),
  scheduled_for, processor_ref, created_at`.
- **Dispute** — a buyer chargeback against a charge. `id, charge_id, amount
  (Money), status (open|won|lost), created_at`.

## Ledger model (double-entry)

Every money movement is a **JournalEntry** with 2+ **JournalLine**s that MUST
balance: `sum(debits) == sum(credits)`. Accounts:

- `processor_clearing` (asset) — money in transit from the card processor.
- `platform_revenue` (revenue) — accumulated platform fees.
- `processor_fees` (expense) — fees paid to the processor.
- `seller_payable:{seller_id}` (liability) — what Obol owes each seller.
- `platform_reserve:{platform_id}` (liability) — held funds / risk reserve.

**Settlement posting** (on `payment.settled` for charge amount A, platform fee
P, processor fee F, seller net N = A − P − F):

```
DEBIT  processor_clearing            A
CREDIT platform_revenue             P
CREDIT processor_fees (contra)      F      # modeled as credit to clearing offset
CREDIT seller_payable:{seller}      N
```

**Refund reversal** (on `refund.completed` for amount R, proportional fee
give-back p): a mirror-image entry that debits `seller_payable` and
`platform_revenue` and credits `processor_clearing`. Refunds never delete the
original entry — they post a new, opposite one (immutable journal).

## Events (gateway publishes → ledger consumes; console reads projections)

All events share an envelope: `{ id, type, ts, data }`. Types + `data`:

- `payment.authorized` — `{ charge_id, platform_id, seller_id, amount,
  platform_fee, processor_fee }`
- `payment.settled` — `{ charge_id, platform_id, seller_id, amount,
  platform_fee, processor_fee }`  → **ledger posts the settlement entry**
- `refund.completed` — `{ refund_id, charge_id, amount }`  → **ledger posts
  the reversal entry**
- `payout.scheduled` — `{ batch_id, seller_id, amount, scheduled_for }`
- `payout.paid` — `{ batch_id, seller_id, amount, processor_ref }`  → **ledger
  marks the batch paid and debits seller_payable**

Ordering: events for a single charge are causally ordered (authorized before
settled before refunded). Consumers must be idempotent on `event.id`.

## The three repos

### obol-gateway (Go) — the payment API edge
Public REST API. Owns charges, refunds, idempotency, the processor adapter,
fee/pricing computation, and event publishing. Never does accounting itself.

Key endpoints:
- `POST /v1/charges` (requires `Idempotency-Key` header) → authorize + settle
- `GET  /v1/charges/{id}`
- `POST /v1/charges/{id}/refunds`
- `POST /v1/payouts` (execute a seller payout via the processor)
- webhook publisher → emits the events above

Ground-truth locations (tests reference these):
- **fee/pricing computation** lives in gateway `pricing` package.
- **idempotency** store lives in gateway `idempotency` package.
- **processor adapter** (charge/refund/payout to the "card network") in
  gateway `processor` package (a deterministic mock processor).

### obol-ledger (Python / FastAPI) — double-entry accounting core
Consumes gateway events and posts journal entries. Exposes balances,
statements, and payout batches. Enforces the balance invariant.

Key endpoints:
- `POST /internal/events` — consume an event envelope
- `GET  /v1/accounts/{account_id}/balance`
- `GET  /v1/accounts/{account_id}/statement`
- `POST /v1/payout-batches` — build a batch from a seller's payable balance
- `GET  /v1/payout-batches/{batch_id}`

Ground-truth locations:
- **settlement + refund posting** lives in ledger `posting` module.
- **balance derivation** in ledger `balances` module.
- **payout batch building** in ledger `payouts` module (calls gateway
  `POST /v1/payouts` to actually move money).

### obol-console (TypeScript / React + Express BFF) — merchant dashboard
The platform operator's UI. Reads from gateway + ledger via a Node BFF; never
touches the processor directly.

Key screens: Transactions, Balances, Payouts, Disputes, and a **Refund**
action. BFF proxies: refund → gateway; balances/statements/payouts → ledger.

Ground-truth locations:
- **refund action** in console `RefundButton` component → BFF `refunds` route
  → gateway `POST /v1/charges/{id}/refunds`.
- **balance display** in console `BalancePage` → BFF `balances` route →
  ledger `GET /v1/accounts/{id}/balance`.

## Cross-repo relationships (the point — every one has a ground-truth answer)

1. **Refund flow spans all 3 repos:** console `RefundButton` → BFF → gateway
   refund handler → `processor.refund` → emit `refund.completed` → ledger
   posting posts the reversal entry. A question about "how a refund flows end
   to end" must retrieve code from console, gateway, AND ledger.
2. **Fee: computed vs recorded (gateway ↔ ledger):** gateway `pricing`
   computes `platform_fee`; ledger `posting` records it to `platform_revenue`.
3. **Idempotency (gateway):** the `Idempotency-Key` header is stored/checked in
   gateway `idempotency` before any processor call.
4. **Payout batching (ledger → gateway):** ledger `payouts` builds a batch from
   `seller_payable` balance, calls gateway `POST /v1/payouts`, gateway emits
   `payout.paid`, ledger marks the batch paid.
5. **Balance read (console → ledger):** console `BalancePage` → BFF → ledger
   `balances`.

## Fixed sample data (used by all repos + docs so examples line up)

- Platform: `plat_marisqueira` — "Marisqueira Marketplace", country `PT`,
  `default_platform_fee_bps = 290` (2.9%).
- Sellers: `sell_atelier` ("Atelier Costa", verified, EUR),
  `sell_ceramica` ("Cerâmica do Vale", verified, EUR).
- Example charge: `chg_0001` — seller `sell_atelier`, amount `{ 12000, "EUR" }`
  (€120.00), platform_fee `{ 348, "EUR" }` (€3.48), processor_fee
  `{ 205, "EUR" }`, seller net `{ 11447, "EUR" }`.

## Conventions

- IDs are prefixed snake ids: `chg_`, `rfnd_`, `pyt_`, `sell_`, `plat_`,
  `evt_`, `acct_`, `jrnl_`.
- Timestamps are RFC-3339 UTC.
- All monetary math in minor units, integer, banker's rounding for fees.
- Currencies in the examples: EUR (sellers) with the platform in PT.
