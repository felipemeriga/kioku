# Architecture Decision Records

> This document collects the significant architectural decisions behind Obol, in
> the standard ADR format: **Context** (the forces at play), **Decision** (what we
> chose), and **Consequences** (what follows, good and bad). ADRs are immutable
> once accepted — if a decision is revisited, a new ADR supersedes the old one
> rather than editing it, mirroring the immutable-journal philosophy of the
> ledger itself.
>
> Companion reading: the ledger model these ADRs shape is in
> [05 — Ledger Model and Invariants](05-ledger-model-and-invariants.md); money and
> fees in [06 — Money Movement and Fees](06-money-movement-and-fees.md); events in
> [07 — Event Catalog](07-event-catalog.md); payouts and reconciliation in
> [08 — Payouts and Reconciliation](08-payouts-and-reconciliation.md); security in
> [09 — Security and Compliance](09-security-and-compliance.md).

## Index

| ADR | Title | Status |
| --- | ----- | ------ |
| [ADR-001](#adr-001-double-entry-ledger-over-single-entry-balances) | Double-entry ledger over single-entry balances | Accepted |
| [ADR-002](#adr-002-money-as-integer-minor-units) | Money as integer minor units | Accepted |
| [ADR-003](#adr-003-idempotency-keys-on-charges) | Idempotency keys on charges | Accepted |
| [ADR-004](#adr-004-event-driven-ledger-vs-synchronous-posting) | Event-driven ledger vs synchronous posting | Accepted |
| [ADR-005](#adr-005-immutable-journal-with-reversal-entries) | Immutable journal with reversal entries | Accepted |
| [ADR-006](#adr-006-basis-points-fees-with-bankers-rounding) | Basis-points fees with banker's rounding | Accepted |
| [ADR-007](#adr-007-bff-pattern-for-the-console) | BFF pattern for the console | Accepted |
| [ADR-008](#adr-008-in-region-data-residency-eu-sellers) | In-region data residency (EU sellers) | Accepted |

---

## ADR-001: Double-entry ledger over single-entry balances

**Status:** Accepted

### Context

Obol's core job is to know, at every instant and with proof, how much it owes each
seller and how much revenue the platform has earned. The simplest design keeps a
single mutable integer balance per seller and per account, adjusting it up and
down as charges, refunds, and payouts occur. That design has a fatal flaw for a
payments company: a stored balance has nothing to check it against. A dropped
update, a double-applied refund, a partial write, or a race between workers
silently corrupts the number, and there is no built-in contradiction to detect
the corruption. Money errors that go undetected become customer-money losses.

### Decision

Use a **double-entry ledger**. Every money movement is a `JournalEntry` composed
of two or more `JournalLine`s that must satisfy `sum(debits) == sum(credits)`.
Balances are **derived** by folding over the immutable lines, not stored and
mutated. The five-account chart (`processor_clearing`, `platform_revenue`,
`processor_fees`, `seller_payable:{id}`, `platform_reserve:{id}`) and the balance
invariant are specified in
[05 — Ledger Model and Invariants](05-ledger-model-and-invariants.md).

### Consequences

- **(+)** Every entry must balance, so a large class of bugs is caught at write
  time, before bad data can be read. The books can never silently drift out of
  internal consistency.
- **(+)** Balances are reproducible: replaying the journal from zero always yields
  the same numbers, which makes the ledger an audit source of truth (see
  [09 — Security and Compliance §audit-log](09-security-and-compliance.md#audit-log)).
- **(+)** Corrections and refunds are expressible as new entries, not edits (see
  [ADR-005](#adr-005-immutable-journal-with-reversal-entries)).
- **(−)** More rows written per movement (four lines for a settlement) and more
  accounting discipline required from engineers.
- **(−)** Deriving balances from history needs a snapshot/checkpoint optimization
  to stay fast (documented in
  [05 — Ledger Model and Invariants §7](05-ledger-model-and-invariants.md#7-how-balances-are-derived)).

For a company whose product *is* correct money-tracking, the write-time safety
net is worth the extra rows.

---

## ADR-002: Money as integer minor units

**Status:** Accepted

### Context

Monetary amounts must be exact. Floating-point representations (`120.0`) cannot
represent many decimal fractions exactly and accumulate rounding error under
arithmetic — unacceptable when the whole point is to reconcile to the cent against
a processor. We need one representation that is exact, unambiguous, and identical
across the Go gateway, the Python ledger, and the TypeScript console.

### Decision

Represent all money as **integer minor units plus an ISO-4217 currency**, using
the canonical shape `Money { amount_minor: int64, currency: string }` in every
language. €120.00 is `{ 12000, "EUR" }`, never `120.0`. Arithmetic is integer-only
and permitted **only between same-currency `Money`**; cross-currency operations are
rejected at the boundary. Rounding occurs exactly once per fee, at the
basis-points division (see
[ADR-006](#adr-006-basis-points-fees-with-bankers-rounding) and
[06 — Money Movement and Fees §6](06-money-movement-and-fees.md#6-currency-handling-rules)).

### Consequences

- **(+)** No floating-point drift; exact arithmetic end to end.
- **(+)** A single, language-agnostic shape means an amount serialized by the
  gateway deserializes identically in the ledger and console — the `Money` in an
  event payload ([07 — Event Catalog](07-event-catalog.md)) is unambiguous.
- **(+)** The seller-net remainder `N = A − P − F` is exact integer subtraction,
  which is what keeps `P + F + N == A` a hard equality and keeps settlement
  entries balanced by construction.
- **(−)** Engineers must remember that `12000` means €120.00, not €12000 — display
  formatting is a presentation concern handled at the edge (console).
- **(−)** Currencies with different minor-unit conventions (e.g. zero-decimal
  currencies) require care; the current sample dataset is EUR-only, which sidesteps
  this, but the `currency` field is always carried so the convention is never
  guessed.

---

## ADR-003: Idempotency keys on charges

**Status:** Accepted

### Context

`POST /v1/charges` moves money. Networks are unreliable: a client may not receive
the response and retry, or a proxy may replay a request. Without protection, a
retry creates a *second* charge and the buyer is charged twice. This must be
impossible.

### Decision

Require an **`Idempotency-Key` header** on `POST /v1/charges`. The gateway
`idempotency` package stores the key and its result, and **checks it before any
processor call**. A repeated request with the same key returns the original
result rather than creating a new charge or calling the processor again. The same
guard pattern is applied to payout execution (`POST /v1/payouts`), keyed on the
batch id (see
[08 — Payouts and Reconciliation §4.1](08-payouts-and-reconciliation.md#41-the-idempotency-guard)).

### Consequences

- **(+)** A retried charge can never double-charge a buyer; a retried payout can
  never double-pay a seller. This is the foundational safety property of the money
  edge.
- **(+)** Clients can retry freely on uncertain outcomes, which simplifies client
  logic and improves resilience.
- **(−)** The gateway must persist idempotency records and define their retention
  window; a key reused after expiry behaves as new.
- **(−)** This is distinct from, and does not replace, **event-level idempotency**
  in the ledger (keyed on `event.id`). A single charge created once can still emit
  a `payment.settled` event delivered twice; only `event.id` dedupe protects the
  posting. The two mechanisms operate at different layers and are both required
  (see [07 — Event Catalog §8](07-event-catalog.md#8-idempotency-and-delivery-semantics)).

---

## ADR-004: Event-driven ledger vs synchronous posting

**Status:** Accepted

### Context

When a charge settles, the ledger must post the settlement entry. One option is
for the gateway to call the ledger **synchronously** inside the charge request —
the charge doesn't return until the ledger has posted. The alternative is for the
gateway to **emit an event** that the ledger consumes asynchronously. Synchronous
posting couples the availability of the money edge to the availability of the
accounting core: if the ledger is down or slow, charges fail or hang, even though
the money movement at the processor already succeeded.

### Decision

Make the ledger **event-driven**. The gateway is the sole producer; it emits
`payment.settled`, `refund.completed`, `payout.paid`, etc.
([07 — Event Catalog](07-event-catalog.md)). The ledger consumes them at
`POST /internal/events` and posts entries. Delivery is **at-least-once**, and
correctness under redelivery rests on **idempotency keyed on `event.id`** — the
ledger stamps each `JournalEntry` with its `event_id` and refuses to post twice
for the same id.

### Consequences

- **(+)** The money edge and the accounting core are decoupled: a ledger outage
  delays postings but does not fail charges. Events are durable and replayed when
  the ledger recovers.
- **(+)** The ledger can be scaled and deployed independently, and can rebuild
  projections by replaying events.
- **(+)** Reconciliation and recovery are natural: a lost `payout.paid` can simply
  be re-driven ([08 — Payouts and Reconciliation §7.1](08-payouts-and-reconciliation.md#71-a-batch-is-stuck-in-processing)).
- **(−)** Eventual consistency: for a brief window a charge is settled at the
  processor but not yet posted in the ledger. The console must tolerate this (it
  reads projections that may lag slightly).
- **(−)** At-least-once delivery makes idempotency non-optional; every consumer
  *must* dedupe on `event.id`. Getting this wrong double-posts money.
- **(−)** Ordering is only guaranteed within a causal chain (per charge, per
  batch), not globally — consumers must not assume a global total order (see
  [07 — Event Catalog §9](07-event-catalog.md#9-ordering-and-causality-summary)).

---

## ADR-005: Immutable journal with reversal entries

**Status:** Accepted

### Context

Money movements sometimes need to be undone (a refund) or corrected (a mistaken
posting). The tempting approach is to update or delete the offending
`JournalEntry`. But a ledger that can rewrite its own history is not an audit
trail — an auditor (or an incident responder) can no longer trust that what the
ledger shows is what actually happened, and a bug or a bad actor could quietly
erase evidence.

### Decision

Make the journal **append-only**. Entries are **never updated and never deleted**.
A refund posts a *new* `refund_reversal` entry that is the mirror image of the
amounts being given back; the original settlement entry is untouched. Corrections
likewise post a compensating reversal followed by the correct entry. The economic
state of anything (a charge, a seller balance) is the *sum* of its immutable
entries, not the latest value of a mutable record.

### Consequences

- **(+)** The ledger is a trustworthy audit source of truth: history cannot be
  silently rewritten, which underpins incident response and compliance (see
  [09 — Security and Compliance](09-security-and-compliance.md)).
- **(+)** Reconciliation discrepancies are resolved by posting correcting entries,
  keeping the full story visible — the mistake *and* the fix
  ([08 — Payouts and Reconciliation §6.3](08-payouts-and-reconciliation.md#63-discrepancy-handling)).
- **(+)** A full refund of `chg_0001` returns every account to zero via a mirror
  reversal without editing the settlement (worked in
  [05 — Ledger Model and Invariants §9](05-ledger-model-and-invariants.md#9-worked-example--full-refund-reversal-of-chg_0001)).
- **(−)** More entries accumulate over time; a fully-refunded charge has two (or
  more) entries whose sum is zero, rather than a single deleted record.
- **(−)** "Current state" is always a derivation, never a direct read — which is
  consistent with [ADR-001](#adr-001-double-entry-ledger-over-single-entry-balances)
  and requires the balance-derivation machinery to be efficient.

---

## ADR-006: Basis-points fees with banker's rounding

**Status:** Accepted

### Context

The platform fee is a percentage of the charge amount. Two things must be pinned
down: how the rate is expressed, and how the fractional-cent result is rounded.
Percentages as floats (`0.029`) reintroduce the float problems ADR-002 avoids, and
a biased rounding rule (round-half-up) systematically over-collects fees by a
fraction of a cent per rounded charge — across millions of charges that is real,
detectable, and embarrassing money that doesn't reconcile.

### Decision

Express fee rates in **basis points** (integer; 1 bps = 0.01%, so 2.9% = `290`
bps) and compute the fee as:

```
platform_fee = round_half_even( amount_minor * platform_fee_bps / 10000 )
```

using **banker's rounding (round half to even)**. Rounding happens exactly once,
at this division; every other monetary operation is exact integer arithmetic. The
platform's rate is `default_platform_fee_bps` (the sample platform
`plat_marisqueira` uses `290`), overridable per charge. Detailed rounding cases
and worked examples are in
[06 — Money Movement and Fees §2](06-money-movement-and-fees.md#2-the-basis-points-fee-formula).

### Consequences

- **(+)** Integer bps rates avoid float drift and are exact.
- **(+)** Round-half-to-even has zero directional bias — half-way cases round up
  half the time and down half the time — so expected rounding error is zero and
  fees reconcile cleanly against an independent recomputation.
- **(+)** The canonical sample reconciles exactly: `round_half_even(12000 * 290 /
  10000) = round_half_even(348.0) = 348` (€3.48), giving seller net
  `12000 − 348 − 205 = 11447` (€114.47).
- **(−)** Engineers who expect "round up on .5" will be surprised by banker's
  rounding; the rule must be documented and tested (it is).
- **(−)** Proportional fee give-backs on partial refunds also use banker's
  rounding per fee, with the seller clawback taken as the exact remainder so the
  reversal still balances (see
  [06 — Money Movement and Fees §4](06-money-movement-and-fees.md#4-the-refund-give-back)).

---

## ADR-007: BFF pattern for the console

**Status:** Accepted

### Context

The merchant console is a React single-page app that needs data from **two**
backends — the gateway (charges, refunds) and the ledger (balances, statements,
payouts). Letting the browser call both services directly would spread auth,
CORS, and aggregation logic into the frontend, expose internal service topology to
the client, and tempt someone to give the browser credentials it should never
hold. It would also couple the UI tightly to each backend's exact API shape.

### Decision

Put a **Backend-for-Frontend (BFF)** — a Node/Express server — between the React
app and the backends. The console UI talks only to the BFF; the BFF authenticates
and authorizes the operator, then proxies: **refund → gateway**;
**balances/statements/payouts → ledger**. The console (and thus the BFF) **never
touches the processor directly** and holds no processor credentials. Concretely,
`RefundButton` → BFF `refunds` route → gateway `POST /v1/charges/{id}/refunds`,
and `BalancePage` → BFF `balances` route → ledger `GET /v1/accounts/{id}/balance`.

### Consequences

- **(+)** A single trust boundary for the UI: auth, authorization, and aggregation
  live in the BFF, not the browser (see the access-control model in
  [09 — Security and Compliance §6](09-security-and-compliance.md#6-access-control-model)).
- **(+)** Internal service topology is hidden from the client; the BFF can shape
  responses for the UI without leaking backend contracts.
- **(+)** The browser holds no gateway/ledger/processor credentials — removing a
  whole class of "compromised dashboard → drained funds" attacks.
- **(+)** The end-to-end refund flow that spans all three repos runs through this
  BFF hop (console → BFF → gateway → processor → `refund.completed` → ledger),
  giving one place to authorize and audit refunds.
- **(−)** An extra network hop and an extra service to run and secure.
- **(−)** The BFF can become a dumping ground for logic if not disciplined; it
  should proxy and aggregate, not accumulate business rules that belong in the
  gateway or ledger.

---

## ADR-008: In-region data residency (EU sellers)

**Status:** Accepted

### Context

Obol's sellers are EU-based (the sample platform `plat_marisqueira` is in Portugal
with EUR sellers `sell_atelier` and `sell_ceramica`). EU personal data — seller
KYC, bank details, and the transaction records tied to identifiable sellers — is
subject to GDPR and to customer and regulator expectations that EU personal data
stays in the EU. Storing or replicating that data outside the EU creates legal,
contractual, and trust risk.

### Decision

Store and process EU sellers' data **in-region (EU)**. Databases, backups, the
ledger, and KYC stores for EU tenants reside in EU regions. Cross-region
replication of EU personal data outside the EU is **not** performed for these
tenants. Data residency is treated as a hard constraint on deployment topology,
not a best-effort setting (see
[09 — Security and Compliance §9](09-security-and-compliance.md#9-data-residency)).

### Consequences

- **(+)** GDPR data-residency expectations are met by construction; EU personal
  data does not leave the EU.
- **(+)** Simplifies the compliance story for EU platforms and their regulators,
  and reduces breach-notification complexity.
- **(−)** Multi-region expansion (e.g. onboarding non-EU platforms) requires
  region-aware routing and per-region data stores rather than one global store —
  more operational complexity.
- **(−)** Some cross-region conveniences (a single global analytics warehouse over
  raw personal data, global DR into a non-EU region) are constrained; aggregate,
  anonymized, or in-region alternatives must be used instead.
- **(−)** Backups and disaster-recovery targets must themselves be in-region,
  which narrows the DR options and must be verified during any DR exercise.
