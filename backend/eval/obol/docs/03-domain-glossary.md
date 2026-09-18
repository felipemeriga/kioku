# Obol — Domain Glossary

> The precise, canonical definition of every domain term Obol uses. Entity field
> names, states, event types, and the chart of accounts here match the internal
> spec (`SPEC.md`) exactly; if any other doc appears to disagree, this glossary
> and the spec win. Terms are grouped by theme and cross-referenced. For the
> narrative, see [01-product-overview.md](./01-product-overview.md); for how the
> services use these terms, see
> [02-system-architecture.md](./02-system-architecture.md).

## How to read this glossary

- **Entities** are objects with an `id` and fields. IDs are prefixed snake ids
  (see [ID prefixes](#id-prefixes)).
- **States** are the allowed values of a status field and the transitions
  between them.
- **`Money`** always means integer minor units + currency — never a float.
- Cross-references use → and link to the relevant term.

---

## Actors

### Platform
Obol's direct customer: the online marketplace that integrates Obol. The
platform sets its own commission rate, owns the relationship with → Buyers and →
Sellers, and operates the → Console. Never economically owns seller money.

**Entity:** `Platform { id, name, country, default_platform_fee_bps, created_at }`

- `id` — prefixed `plat_`.
- `country` — ISO country code (e.g. `PT`).
- `default_platform_fee_bps` — the platform's commission in → basis points,
  applied to charges unless overridden.

**Sample:** `plat_marisqueira` — "Marisqueira Marketplace", country `PT`,
`default_platform_fee_bps = 290` (2.9%).

Related: → Platform fee, → `platform_revenue`, → `platform_reserve`.

### Seller
A sub-merchant selling through the → Platform's marketplace. Earns the → Seller
net of each → Charge, accrues a → balance (→ `seller_payable`), and is paid out
via → PayoutBatch to a bank account in their `payout_currency`. Must reach → KYC
status `verified` to be paid out.

**Entity:** `Seller { id, platform_id, display_name, kyc_status, payout_currency,
created_at }`

- `id` — prefixed `sell_`.
- `platform_id` — the owning → Platform.
- `kyc_status` — one of `pending | verified | rejected` (→ KYC status).
- `payout_currency` — ISO-4217 currency the seller is paid in.

**Samples:** `sell_atelier` — "Atelier Costa" (`verified`, EUR);
`sell_ceramica` — "Cerâmica do Vale" (`verified`, EUR).

### Buyer
The end customer who pays for an order on the marketplace — the source of the
money behind a → Charge. Obol does not store a rich buyer profile; the buyer
appears as the payer of a charge and as the originator of a → Dispute
(chargeback).

### Obol
The infrastructure provider running the three services — → Gateway, → Ledger, →
Console. Custodian and bookkeeper of the money; never its economic owner.

---

## Money and math

### Money
The universal representation of an amount. **Always** integer minor units plus an
ISO-4217 currency — never a float.

**Shape:** `Money { amount_minor: int64, currency: string }`
e.g. `{ 4999, "USD" }` = $49.99; `{ 12000, "EUR" }` = €120.00.

**Rules:**
- Arithmetic is allowed only between **same-currency** `Money`. Cross-currency
  arithmetic is **rejected**.
- All monetary math is done in minor units, as integers.
- Fee rounding uses banker's rounding (→ round_half_even).

### Minor units
The smallest indivisible unit of a currency — cents for EUR/USD. €120.00 is
`12000` minor units. Obol stores and computes everything in minor units to avoid
floating-point error.

### Basis points (bps)
A unit of rate: **1 bps = 0.01%**. A 2.9% fee is `290` bps. Fee rates such as
`default_platform_fee_bps` are always expressed in bps.

### round_half_even (banker's rounding)
The rounding mode used for fee computation. Rounds to the nearest integer; on an
exact half, rounds to the nearest **even** integer. This removes the upward bias
of always-round-half-up across many charges.

Used in: → Platform fee computation.

### Platform fee
The → Platform's commission on a → Charge, computed as:

```
platform_fee = round_half_even(charge_amount * platform_fee_bps / 10000)
```

**Worked example (sample charge `chg_0001`):**
`round_half_even(12000 * 290 / 10000)` = `348` → **€3.48**.

Recorded in the ledger to → `platform_revenue`. Computed by the → Gateway's
`pricing` package; **recorded** by the → Ledger's `posting` module. See the
"computed vs recorded" relationship in
[02-system-architecture.md](./02-system-architecture.md).

### Processor fee
The fee paid to the card → Processor for moving the money on a → Charge. On
`chg_0001` it is `{ 205, "EUR" }` → **€2.05**. Recorded to → `processor_fees`.

### Seller net
The → Seller's share of a → Charge: `N = amount − platform_fee − processor_fee`.
On `chg_0001`: `12000 − 348 − 205 = 11447` → **€114.47**. Credited to →
`seller_payable:{seller_id}`.

---

## Payment lifecycle entities

### Charge
A buyer payment for an order, split into → Platform fee, → Processor fee, and →
Seller net. Created via `POST /v1/charges` on the → Gateway.

**Entity:** `Charge { id, platform_id, seller_id, amount (Money), platform_fee
(Money), processor_fee (Money), status, idempotency_key, processor_ref,
created_at }`

- `id` — prefixed `chg_`.
- `idempotency_key` — the value of the `Idempotency-Key` header that created it
  (→ Idempotency).
- `processor_ref` — the → Processor's reference for the payment.

**States and transitions:**

```
   pending ──▶ authorized ──▶ settled ──▶ refunded
      │                          │    └──▶ partially_refunded
      └──▶ failed                └──▶ (via Refund)
```

- `pending` — created, not yet authorized.
- `authorized` — processor approved the payment (emits → `payment.authorized`).
- `settled` — funds captured (emits → `payment.settled`; ledger posts the
  settlement entry).
- `failed` — authorization/settlement failed.
- `refunded` — fully reversed by → Refund(s).
- `partially_refunded` — some but not all of the amount reversed.

**Sample:** `chg_0001` — seller `sell_atelier`, amount `{ 12000, "EUR" }`,
`platform_fee { 348, "EUR" }`, `processor_fee { 205, "EUR" }`, seller net
`{ 11447, "EUR" }`.

### Refund
Reverses all or part of a → Charge. Moves money back to the → Buyer via the →
Processor and triggers a mirror-image ledger entry that gives fees back
proportionally. Refunds never delete the original → JournalEntry — they post a
new, opposite one.

**Entity:** `Refund { id, charge_id, amount (Money), reason, status, created_at }`

- `id` — prefixed `rfnd_`.
- `status` — one of `pending | completed | failed`.

**States:**

```
   pending ──▶ completed   (emits refund.completed → ledger posts reversal)
      └──────▶ failed
```

A completed refund for the full charge amount moves the → Charge to `refunded`;
a partial refund moves it to `partially_refunded`.

Created via `POST /v1/charges/{id}/refunds`. In the → Console, initiated by the
`RefundButton` → BFF → gateway. See the end-to-end refund flow in
[11-integration-guide.md](./11-integration-guide.md).

### Dispute
A → Buyer chargeback against a → Charge — the buyer contests the payment with
their card issuer. Surfaced on the → Console Disputes screen.

**Entity:** `Dispute { id, charge_id, amount (Money), status, created_at }`

- `status` — one of `open | won | lost`.

**States:**

```
   open ──▶ won    (dispute resolved in the platform/seller's favor)
     └────▶ lost   (funds returned to the buyer)
```

A dispute is distinct from a → Refund: a refund is a *voluntary* reversal the
platform initiates; a dispute is a chargeback the *buyer* initiates through
their bank.

---

## Payouts

### PayoutBatch
A scheduled movement of a → Seller's accrued → balance to their bank account.
Built by the → Ledger's `payouts` module from the seller's → `seller_payable`
balance, then executed by the → Gateway via `POST /v1/payouts`.

**Entity:** `PayoutBatch { id, seller_id, amount (Money), status, scheduled_for,
processor_ref, created_at }`

- `id` — prefixed `pyt_`.
- `scheduled_for` — RFC-3339 UTC time the batch is scheduled to run.
- `processor_ref` — the → Processor's reference for the bank movement.

**States:**

```
   scheduled ──▶ processing ──▶ paid   (emits payout.paid → ledger debits
       │                                  seller_payable, marks batch paid)
       └──────────────────────▶ failed
```

- `scheduled` — batch built from balance (emits → `payout.scheduled`).
- `processing` — payout in flight at the processor.
- `paid` — money reached the seller's bank (emits → `payout.paid`).
- `failed` — payout failed; no `seller_payable` debit is posted, balance
  unchanged, retryable next schedule.

### Payout
The act/endpoint of executing a payout on the → Gateway: `POST /v1/payouts`. The
→ Ledger calls this to actually move money for a → PayoutBatch. (The batch is the
record; the payout is the execution.)

---

## Ledger model

### JournalEntry
An atomic, balanced record of one money movement. Contains 2+ → JournalLines
that **must** satisfy `sum(debits) == sum(credits)`. Immutable — corrections are
new opposite entries, never edits.

- `id` — prefixed `jrnl_`.

Posted by the → Ledger's `posting` module on → `payment.settled` (settlement
entry) and → `refund.completed` (reversal entry).

### JournalLine
A single debit or credit against one → account within a → JournalEntry. Carries
an amount in → minor units and an account. Balances are derived by summing
journal lines per account.

### Account / Chart of accounts
The fixed set of accounts every → JournalLine posts against. `id` prefixed
`acct_` where applicable.

| Account | Type | Meaning |
|---|---|---|
| `processor_clearing` | asset | money in transit from the card → Processor |
| `platform_revenue` | revenue | accumulated → Platform fees |
| `processor_fees` | expense | fees paid to the → Processor |
| `seller_payable:{seller_id}` | liability | what Obol owes each → Seller |
| `platform_reserve:{platform_id}` | liability | held funds / risk reserve for a → Platform |

**Settlement posting** (on → `payment.settled`; amount A, platform fee P,
processor fee F, seller net N = A − P − F):

```
DEBIT  processor_clearing            A
CREDIT platform_revenue              P
CREDIT processor_fees (contra)       F    # modeled as credit to clearing offset
CREDIT seller_payable:{seller}       N
```

**Refund reversal** (on → `refund.completed`; amount R, proportional fee
give-back p): a mirror-image entry debiting `seller_payable` and
`platform_revenue`, crediting `processor_clearing`.

### Balance
The current position of an → account, **derived** by summing its → JournalLines
— not a stored counter. Exposed by the → Ledger at
`GET /v1/accounts/{account_id}/balance`. Because it is derived from the immutable
journal, it cannot drift. In the → Console, shown on the Balances screen via the
`BalancePage` → BFF → ledger.

### Statement
The ordered list of → JournalLines for an → account over time, exposed at
`GET /v1/accounts/{account_id}/statement`. The auditable history behind a →
balance.

---

## KYC and compliance

### KYC (Know Your Customer)
The identity-verification a → Seller must pass before Obol will pay them out.

### KYC status
The `kyc_status` field on a → Seller, one of:

- `pending` — verification not yet completed; seller cannot be paid out.
- `verified` — seller passed KYC; eligible for → PayoutBatch execution.
- `rejected` — seller failed KYC; not eligible for payout.

Both sample sellers (`sell_atelier`, `sell_ceramica`) are `verified`.

---

## Events

### Event / envelope
The message the → Gateway publishes and the → Ledger consumes. Shared envelope:
`{ id, type, ts, data }`.

- `id` — prefixed `evt_`. Consumers are **idempotent on `event.id`** — a
  duplicate delivery must not double-post.
- `ts` — RFC-3339 UTC.
- `type` + `data` — see the table below.

**Ordering:** events for a single → Charge are causally ordered — `authorized`
before `settled` before refund/reversal.

| Type | `data` | Ledger effect |
|---|---|---|
| `payment.authorized` | `{ charge_id, platform_id, seller_id, amount, platform_fee, processor_fee }` | record only |
| `payment.settled` | `{ charge_id, platform_id, seller_id, amount, platform_fee, processor_fee }` | **posts settlement entry** |
| `refund.completed` | `{ refund_id, charge_id, amount }` | **posts reversal entry** |
| `payout.scheduled` | `{ batch_id, seller_id, amount, scheduled_for }` | record only |
| `payout.paid` | `{ batch_id, seller_id, amount, processor_ref }` | **marks batch paid, debits `seller_payable`** |

---

## Services

### Gateway (obol-gateway)
The Go payment API edge. Owns the public REST API, fee/pricing computation
(`pricing`), → Idempotency (`idempotency`), the → Processor adapter
(`processor`), and event publishing. Never does accounting itself. See
[02-system-architecture.md](./02-system-architecture.md) §2.1.

### Ledger (obol-ledger)
The Python/FastAPI double-entry accounting core. Consumes events, posts
→ JournalEntries (`posting`), derives → balances (`balances`), builds →
PayoutBatches (`payouts`). Enforces the balance invariant. See §2.2.

### Console (obol-console)
The TypeScript/React + Express BFF merchant dashboard. Screens: Transactions,
Balances, Payouts, Disputes, plus a Refund action. Reads gateway + ledger via
the BFF; never touches the → Processor. See §2.3.

### BFF (backend-for-frontend)
The Express server behind the → Console SPA. Proxies refund → gateway;
balances/statements/payouts → ledger.

### Processor
The card network / bank rails. In Obol it is a **deterministic mock** in the
gateway's `processor` package that authorizes, settles, refunds, and pays out.

---

## Idempotency

### Idempotency
The guarantee that retrying a request does not repeat its effect. On the →
Gateway, `POST /v1/charges` requires an `Idempotency-Key` header; the key is
stored and checked in the `idempotency` package **before any → Processor call**,
so a retried charge returns the original result instead of charging twice. The
resulting → Charge records the key as `idempotency_key`.

Separately, event → consumers are **idempotent on `event.id`** so at-least-once
delivery cannot double-post.

---

## ID prefixes

| Prefix | Entity |
|---|---|
| `plat_` | → Platform |
| `sell_` | → Seller |
| `chg_` | → Charge |
| `rfnd_` | → Refund |
| `pyt_` | → PayoutBatch |
| `evt_` | → Event |
| `acct_` | → Account |
| `jrnl_` | → JournalEntry |

## Conventions

- Timestamps: RFC-3339 UTC.
- Money: integer minor units, banker's rounding (→ round_half_even) for fees.
- Example currency: EUR (sellers), platform in `PT`.
