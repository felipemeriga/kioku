# Obol — System Architecture

> Audience: engineers building on, operating, or extending Obol. This document
> describes the three services, their boundaries, and how data flows through
> them. It derives from the canonical domain spec (`SPEC.md`). For product
> context see [01-product-overview.md](./01-product-overview.md); for terms see
> [03-domain-glossary.md](./03-domain-glossary.md); for the public API see
> [04-gateway-api-reference.md](./04-gateway-api-reference.md).

## 1. The shape in one picture

Obol is three services. One faces the outside world synchronously, one keeps the
books event-drivenly, and one is a dashboard for the platform's operators.

```
                         card processor (mock)
                                  ▲
                                  │ authorize / settle / refund / payout
                                  │
   platform's ┌──────────────────┴───────────────────┐
   backend ──▶│            obol-gateway (Go)          │
  (REST +     │  charges · refunds · payouts · fees   │
  Idempotency │  idempotency · processor adapter      │
   -Key)      │  event publisher                      │
              └───────┬───────────────────────┬───────┘
                      │ emits events           │ POST /v1/payouts (called back)
                      │ (payment.*, refund.*,  │
                      │  payout.*)             │
                      ▼                        │
              ┌───────────────────────────┐   │
              │    obol-ledger (Python)    │──┘
              │  POST /internal/events     │  builds payout batches,
              │  double-entry posting      │  calls gateway to move money
              │  balances · statements     │
              │  payout batches            │
              └───────────▲────────────────┘
                          │ GET balances / statements / payout-batches
                          │
              ┌───────────┴────────────────┐
   operator ─▶│   obol-console (TS/React)  │
   browser    │   React SPA + Express BFF  │
              │   Transactions · Balances  │
              │   Payouts · Disputes       │
              │   Refund action            │
              └────────────────────────────┘
                  BFF proxies:
                    refund      → gateway
                    balances    → ledger
                    statements  → ledger
                    payouts     → ledger
```

The rest of this document walks each box, then the two flows that matter most:
**a charge** and **a payout**.

## 2. The three services

### 2.1 obol-gateway (Go) — the payment API edge

**Responsibility.** The gateway is the only service the platform's backend talks
to for money movement. It owns:

- The **public REST API**: `POST /v1/charges`, `GET /v1/charges/{id}`,
  `POST /v1/charges/{id}/refunds`, `POST /v1/payouts`.
- **Fee / pricing computation** — the `pricing` package. Given a charge amount
  and the platform's `default_platform_fee_bps`, it computes `platform_fee`
  using banker's rounding on integer minor units.
- **Idempotency** — the `idempotency` package. The `Idempotency-Key` header is
  stored and checked *before any processor call*, so retries never double-charge.
- **The processor adapter** — the `processor` package, a deterministic mock of
  the "card network" that authorizes, settles, refunds, and pays out.
- **Event publishing** — the webhook publisher that emits `payment.authorized`,
  `payment.settled`, `refund.completed`, `payout.scheduled`, and `payout.paid`.

**What it explicitly does not do:** the gateway **never does accounting itself.**
It computes fees and emits facts; the ledger interprets those facts into journal
entries. This separation is deliberate — it keeps the correctness-critical
double-entry logic in exactly one place.

**Why Go.** The gateway is latency-sensitive, high-concurrency, and I/O bound on
the processor and the event bus. Go's goroutine model, fast startup, and simple
static binaries make it a good fit for the edge tier, which we want to scale
horizontally and deploy densely.

### 2.2 obol-ledger (Python / FastAPI) — the double-entry accounting core

**Responsibility.** The ledger consumes gateway events and turns them into
balanced journal entries. It owns:

- **Event consumption** — `POST /internal/events` accepts an event envelope
  `{ id, type, ts, data }`. Consumers are **idempotent on `event.id`**.
- **Settlement + refund posting** — the `posting` module. On `payment.settled`
  it posts the settlement entry; on `refund.completed` it posts the mirror-image
  reversal. It enforces the balance invariant: `sum(debits) == sum(credits)`.
- **Balance derivation** — the `balances` module. A balance is *derived* by
  summing an account's journal lines, exposed at
  `GET /v1/accounts/{account_id}/balance` and `.../statement`. There is no
  stored balance counter to drift.
- **Payout batch building** — the `payouts` module. `POST /v1/payout-batches`
  builds a batch from a seller's `seller_payable` balance, then calls the
  gateway's `POST /v1/payouts` to actually move the money.

**The chart of accounts** the ledger posts against:

| Account | Type | Meaning |
|---|---|---|
| `processor_clearing` | asset | money in transit from the card processor |
| `platform_revenue` | revenue | accumulated platform fees |
| `processor_fees` | expense | fees paid to the processor |
| `seller_payable:{seller_id}` | liability | what Obol owes each seller |
| `platform_reserve:{platform_id}` | liability | held funds / risk reserve |

**Why Python / FastAPI.** The ledger is where correctness dominates over raw
throughput. Python keeps the accounting rules readable and testable; FastAPI
gives typed request/response models for the internal event and query API. The
ledger scales less aggressively than the gateway and benefits from clarity over
cleverness.

### 2.3 obol-console (TypeScript / React + Express BFF) — the merchant dashboard

**Responsibility.** The console is the platform operator's UI. It is a React SPA
backed by a thin **Express BFF** (backend-for-frontend). It **never touches the
processor directly** and holds no accounting logic of its own — it reads
projections from the gateway and ledger and offers exactly one write action
(refund).

Key screens: **Transactions, Balances, Payouts, Disputes**, plus a **Refund**
action.

The BFF is purely a proxy/aggregation layer:

- **Refund** — the `RefundButton` component → BFF `refunds` route → gateway
  `POST /v1/charges/{id}/refunds`.
- **Balances** — the `BalancePage` → BFF `balances` route → ledger
  `GET /v1/accounts/{id}/balance`.
- **Statements / Payouts** — BFF routes → ledger.

**Why TypeScript / React + a BFF.** The dashboard is a data-dense operator tool;
React handles the UI, and the Express BFF lets the browser hit one origin while
fan-out to gateway and ledger stays server-side (keeping API keys and internal
URLs off the client).

## 3. The synchronous vs event-driven boundary

This is the single most important architectural line in Obol.

- **Synchronous (request/response):** everything between the platform and the
  gateway, and everything the console BFF reads. When the platform creates a
  charge, it gets an authoritative response *now*. When the console loads
  balances, it reads them *now*. Synchronous calls are where users wait.

- **Event-driven (asynchronous):** everything between the gateway and the
  ledger. The gateway does not call the ledger to post accounting; it **emits an
  event** and returns. The ledger consumes that event and posts the journal
  entry on its own clock.

```
   SYNCHRONOUS EDGE                 EVENT-DRIVEN CORE
   ───────────────                  ─────────────────
   platform ─▶ gateway ─▶ processor
                  │
                  └─ emit event ─────────▶ ledger posts entry
                     (fire, return)         (consume, idempotent)

   console BFF ─▶ gateway (refund, sync)
   console BFF ─▶ ledger  (balances/statements/payouts, sync reads)
```

**Why split it this way.** The processor call is the slow, failure-prone part of
a charge, and the platform needs a fast, authoritative answer about the payment.
The accounting, by contrast, must be *exactly right* but can be *eventually*
consistent by milliseconds-to-seconds. By making the gateway→ledger boundary
event-driven:

- The edge stays fast and available even if the ledger is briefly slow.
- The ledger can be idempotent and replay-safe (idempotent on `event.id`),
  which is exactly what a double-entry core needs.
- Events give an immutable causal record: `payment.authorized` before
  `payment.settled` before `refund.completed`, per charge.

**The one exception — the payout callback.** Payout batching inverts the usual
direction: the *ledger* initiates by calling the gateway's `POST /v1/payouts`
synchronously to move money, and the gateway then emits `payout.paid`, which the
ledger consumes to mark the batch paid. This is the one place the ledger makes an
outbound synchronous call. See §5.

## 4. Data flow: a charge

A buyer pays €120.00 on Marisqueira Marketplace. This produces the fixed sample
charge `chg_0001` (seller `sell_atelier`, amount `{ 12000, "EUR" }`).

```
platform          gateway                  processor        ledger
   │                 │                         │               │
   │ POST /v1/charges│                         │               │
   │ Idempotency-Key │                         │               │
   ├────────────────▶│                         │               │
   │                 │ 1. idempotency check    │               │
   │                 │    (store key first)    │               │
   │                 │ 2. pricing: fee split   │               │
   │                 │    platform_fee=348     │               │
   │                 │    processor_fee=205    │               │
   │                 │ 3. authorize ──────────▶│               │
   │                 │◀──────────── authorized │               │
   │                 │─ emit payment.authorized ──────────────▶│ (record, no post)
   │                 │ 4. settle ─────────────▶│               │
   │                 │◀─────────────── settled │               │
   │                 │─ emit payment.settled ─────────────────▶│ 5. POST the
   │                 │                         │               │    settlement
   │ 201 Created     │                         │               │    JournalEntry
   │◀────────────────┤                         │               │
   │ chg_0001        │                         │               │
```

**Step 5 — the settlement posting.** On `payment.settled` with amount A=12000,
platform fee P=348, processor fee F=205, seller net N = A − P − F = 11447, the
ledger `posting` module writes one balanced `JournalEntry`:

```
DEBIT  processor_clearing              12000
CREDIT platform_revenue                  348
CREDIT processor_fees (contra)           205   # credit to clearing offset
CREDIT seller_payable:sell_atelier     11447
                                       ─────
              debits 12000 == credits 12000  ✓
```

After this, `sell_atelier`'s payable balance is €114.47. The console's
Transactions screen shows the settled `chg_0001`; the Balances screen shows the
seller's accrued €114.47, read live from the ledger.

Full request/response bodies for this flow are in
[04-gateway-api-reference.md](./04-gateway-api-reference.md); the integrating
platform's view of it is in
[11-integration-guide.md](./11-integration-guide.md).

## 5. Data flow: a payout

Payouts run on a schedule. This is the flow where the ledger initiates and the
gateway executes — the inverse of a charge.

```
scheduler       ledger (payouts)        gateway            processor      ledger (posting)
   │                 │                      │                   │               │
   │ time to pay     │                      │                   │               │
   │ sell_atelier    │                      │                   │               │
   ├────────────────▶│                      │                   │               │
   │                 │ 1. read seller_payable balance           │               │
   │                 │    (11447 EUR)       │                   │               │
   │                 │ 2. build PayoutBatch │                   │               │
   │                 │    status=scheduled  │                   │               │
   │                 │─ emit payout.scheduled ─────────────────────────────────▶│ (record)
   │                 │ 3. POST /v1/payouts ─▶│                   │               │
   │                 │                      │ 4. processor.payout ─▶│           │
   │                 │                      │◀──────────── paid  │               │
   │                 │◀───── 200 paid ──────┤                   │               │
   │                 │                      │─ emit payout.paid ──────────────▶│ 5. mark batch
   │                 │                      │                   │               │    paid, DEBIT
   │                 │                      │                   │               │    seller_payable
```

**Step 5 — the payout posting.** On `payout.paid` for the batch, the ledger
marks the `PayoutBatch` `paid` and debits `seller_payable:sell_atelier` by the
paid amount, reducing what Obol owes the seller back toward zero. The money has
left Obol's custody and reached the seller's bank.

Batch states move `scheduled → processing → paid`, or `failed`. On `failed`, no
`seller_payable` debit is posted, so the seller's balance is unchanged and the
batch can be retried on the next schedule.

## 6. Deployment topology

```
                    ┌───────────────────────────────────────┐
                    │              edge / public              │
   platform ───────▶│  obol-gateway (Go)  ×N replicas         │
   backend          │  behind load balancer, autoscaled       │
                    └───────────┬───────────────┬─────────────┘
                                │ events         │ POST /v1/payouts
                                ▼                │ (from ledger)
                    ┌───────────────────────┐    │
                    │   event bus / queue   │    │
                    └───────────┬───────────┘    │
                                ▼                │
                    ┌───────────────────────┐    │
   operator ───┐    │  obol-ledger (Python) │◀───┘
   browser     │    │  ×M replicas          │
               │    │  Postgres (journal)   │
               ▼    └───────────▲───────────┘
       ┌───────────────┐        │ sync reads
       │ obol-console  │────────┘ (balances/statements/payouts)
       │ React + BFF   │
       │  BFF ─▶ gateway (refund)
       └───────────────┘
```

- **obol-gateway** runs as N stateless replicas behind a load balancer,
  autoscaled on request rate. Its idempotency store and processor adapter are
  the only stateful dependencies on the edge.
- **obol-ledger** runs as M replicas over a Postgres store holding the immutable
  journal. It is the system of record; its consumers are idempotent so replicas
  can consume events safely.
- **event bus / queue** carries gateway→ledger events with at-least-once
  delivery; idempotency on `event.id` makes duplicates harmless.
- **obol-console** serves the React SPA and runs the Express BFF; the BFF is the
  only component that fans out to both gateway and ledger.

Concrete SLA targets, health checks, and capacity assumptions for each tier are
in [12-sla-and-operations.md](./12-sla-and-operations.md).

## 7. Technology choices, summarized

| Service | Language / stack | Why |
|---|---|---|
| obol-gateway | Go | latency-sensitive, high-concurrency edge; cheap static binaries; goroutines for concurrent processor + event I/O |
| obol-ledger | Python / FastAPI | correctness over throughput; readable accounting rules; typed event + query models |
| obol-console | TypeScript / React + Express BFF | data-dense operator UI; BFF keeps fan-out and secrets server-side |
| store (ledger) | Postgres | ACID, immutable append-only journal, derived balances via aggregation |
| gateway↔ledger | event bus (at-least-once) | decouples fast edge from correctness core; replay-safe with `event.id` idempotency |

## 8. Invariants the architecture guarantees

1. **The books always balance.** Every `JournalEntry` satisfies
   `sum(debits) == sum(credits)`; the ledger rejects anything that does not.
2. **No double-charge.** The `Idempotency-Key` is stored and checked *before*
   any processor call.
3. **No double-post.** Event consumers are idempotent on `event.id`; at-least-
   once delivery cannot double-count money.
4. **Immutable audit trail.** Refunds and reversals post *new, opposite*
   entries; nothing is ever deleted or mutated in place.
5. **Balances cannot drift.** They are derived from journal lines, not stored
   counters.
6. **Accounting lives in one place.** The gateway computes fees and emits facts;
   only the ledger posts journal entries.
