# Payouts and Reconciliation

> Audience: engineers in `obol-ledger` (which builds payout batches and
> reconciles the books) and `obol-gateway` (which executes payouts through the
> processor), plus the operations / on-call team. This document covers the payout
> lifecycle end to end, how a batch is built from a seller's payable balance, how
> the ledger drives the gateway to execute the disbursement, retries and failure
> handling, and the daily reconciliation of the ledger against the processor —
> including a concrete runbook.
>
> Companion reading: the accounts and postings touched here are defined in
> [05 — Ledger Model and Invariants](05-ledger-model-and-invariants.md); the
> `payout.scheduled` / `payout.paid` events are in
> [07 — Event Catalog](07-event-catalog.md); fee math behind seller balances is
> in [06 — Money Movement and Fees](06-money-movement-and-fees.md).

## 1. The payout lifecycle

A `PayoutBatch` moves a seller's accrued balance to their bank. Its `status`
field walks a fixed state machine:

```
                 build & execute            processor confirms
   scheduled ───────────────────► processing ───────────────► paid
       │                              │
       │  (never left scheduled)      │  processor rejects / errors
       └──────────────┐               └──────────────┐
                      ▼                              ▼
                   failed  ◄──────────────────────  failed
```

| status       | meaning |
| ------------ | ------- |
| `scheduled`  | The batch has been built from the seller's `seller_payable` balance and is queued to execute at `scheduled_for`. `payout.scheduled` has been emitted. No money has moved; the ledger has posted **no** journal entry yet. |
| `processing` | The ledger has called the gateway to execute the payout and is awaiting the processor's result. Money is in flight. |
| `paid`       | The processor confirmed disbursement. The gateway emitted `payout.paid`; the ledger marked the batch `paid` and posted the payout entry debiting `seller_payable`. Terminal, success. |
| `failed`     | The processor rejected or errored and retries were exhausted. No money moved (or a partial movement was fully reversed). Terminal, failure. Requires operator attention. |

`PayoutBatch` fields (from the spec): `id` (`pyt_...`), `seller_id`, `amount`
(`Money`), `status`, `scheduled_for` (RFC-3339 UTC), `processor_ref`,
`created_at`. The `processor_ref` is populated when the payout reaches `paid` and
is the key used during reconciliation (§6).

## 2. Building a batch from the payable balance

Payout batches are **built by the ledger**, in the `payouts` module, from a
seller's `seller_payable:{seller_id}` balance. This is the spec's cross-repo
relationship #4: "ledger `payouts` builds a batch from `seller_payable` balance,
calls gateway `POST /v1/payouts`, gateway emits `payout.paid`, ledger marks the
batch paid."

The build is triggered by `POST /v1/payout-batches` (ledger endpoint), either on
a schedule or on demand. Steps:

1. **Read the payable balance.** Derive `seller_payable:{seller_id}` using the
   `balances` module (credits − debits, since it's a liability — see
   [05 — Ledger Model and Invariants §7](05-ledger-model-and-invariants.md#7-how-balances-are-derived)).
   This is the maximum the batch can move.
2. **Apply payout policy.** Subtract any held reserve
   (`platform_reserve:{platform_id}` policy), any minimum-payout threshold, and
   any in-flight batch already draining this balance. The result is the
   `amount` to pay out. If it is zero or below the minimum, no batch is created.
3. **Check currency.** The batch `amount.currency` must equal the seller's
   `payout_currency`. Both sample sellers are EUR.
4. **Create the batch** in `scheduled` status with a fresh `pyt_` id and a
   `scheduled_for` timestamp.

Worked example: after `chg_0001` settles and before any refund, Atelier Costa's
`seller_payable:sell_atelier` balance is `11447` (€114.47). With no reserve hold
and above the minimum, the ledger builds:

```
PayoutBatch pyt_0001 {
  id:            "pyt_0001",
  seller_id:     "sell_atelier",
  amount:        { "amount_minor": 11447, "currency": "EUR" },
  status:        "scheduled",
  scheduled_for: "2026-09-18T08:00:00Z",
  processor_ref: null,
  created_at:    "2026-09-17T00:00:00Z"
}
```

At this point the gateway emits `payout.scheduled` (see
[07 — Event Catalog §6](07-event-catalog.md#6-payoutscheduled)). No journal entry
is posted yet — scheduling does not move money.

**Important:** building a batch does *not* immediately debit `seller_payable`. The
liability is only discharged when the payout is actually **paid** (§4). Between
`scheduled` and `paid`, the seller's derived balance still shows the full amount;
the ledger tracks the in-flight batch separately so it doesn't build a second
batch against the same funds (step 2).

## 3. Executing the payout through the gateway

The ledger does not touch the card network. To actually move money it calls the
gateway, which owns the `processor` adapter:

```
ledger payouts module ──► POST /v1/payouts (gateway) ──► processor.payout ──► bank
```

Sequence when the batch reaches its `scheduled_for` time (or is executed on
demand):

1. Ledger transitions the batch `scheduled → processing`.
2. Ledger calls gateway `POST /v1/payouts` with the batch id, seller, and amount.
   This request carries an idempotency guard keyed on the batch id so a retried
   call cannot double-pay (mirrors the charge `Idempotency-Key` design —
   [ADR-003](10-architecture-decision-records.md#adr-003-idempotency-keys-on-charges)).
3. Gateway invokes `processor.payout` (the deterministic mock processor in the
   test environment).
4. On success the gateway emits `payout.paid` carrying the processor's
   `processor_ref`.
5. Ledger consumes `payout.paid` via `POST /internal/events`, marks the batch
   `processing → paid`, records `processor_ref`, and posts the payout journal
   entry.

The payout journal entry (posted on `payout.paid`, from
[07 — Event Catalog §7](07-event-catalog.md#7-payoutpaid)):

```
JournalEntry jrnl_pay_0001  (kind=payout, currency=EUR, event_id=evt_payout_paid_0001)

  DEBIT  seller_payable:sell_atelier    11447    # discharge the liability
  CREDIT processor_clearing             11447    # €114.47 leaves clearing to the bank
```

Balances (`11447 == 11447` ✓). After this entry, `seller_payable:sell_atelier`
returns to zero and `processor_clearing` drops by the disbursed amount — a step
toward the clearing pool netting to zero over a full cycle (§6.1).

## 4. Retries and failure handling

Payouts touch external systems, so they must tolerate transient failure without
double-paying or losing money.

### 4.1 The idempotency guard

Every `POST /v1/payouts` for a given batch uses the **batch id as the idempotency
key**. If the ledger retries because it didn't get a response (timeout, dropped
connection), the gateway recognizes the batch id and returns the *same* result
rather than initiating a second disbursement. This is the single most important
safety property: **a retry can never move money twice.**

### 4.2 Retry policy

- **Ledger → gateway call fails or times out:** the ledger retries `POST
  /v1/payouts` with exponential backoff (e.g. 1s, 2s, 4s, capped), keeping the
  batch in `processing`. Because of the batch-id idempotency guard, retries are
  safe. After a bounded number of attempts without a definitive result, the batch
  is left `processing` and flagged for operator review — it is **not**
  auto-failed, because "no response" is ambiguous (the payout may have
  succeeded). See the runbook (§7) for resolving stuck `processing` batches.
- **Processor rejects the payout** (e.g. closed bank account, invalid details):
  the gateway returns a definitive failure. The ledger transitions the batch
  `processing → failed` and posts **no** journal entry (no money moved), leaving
  `seller_payable` intact so the funds remain owed to the seller. The failure is
  surfaced on the console Payouts screen for operator action (fix bank details,
  re-schedule).
- **Partial / in-doubt disbursement:** if the processor reports an ambiguous
  state, the ledger does **not** post a payout entry until the state is resolved
  during reconciliation (§6). The invariant that the books only reflect confirmed
  movements is preserved.

### 4.3 The golden rule of payout state

The ledger posts the `seller_payable` debit **only** on a confirmed `payout.paid`
event — never on `scheduled`, never optimistically on `processing`. This means
the ledger can never over-report a seller as paid. If in doubt, the money is
still owed. Under-reporting (money owed that was actually paid) is caught and
corrected by reconciliation; over-reporting (claiming paid when it wasn't) would
be a customer-money loss and is designed out.

## 5. Why reconciliation is needed

The balance invariant from
[05 — Ledger Model and Invariants §5](05-ledger-model-and-invariants.md#5-the-balance-invariant)
guarantees the ledger agrees *with itself* — every entry balances. It does **not**
guarantee the ledger agrees with the **processor**, the external system that
actually holds and moves the money. The processor could:

- settle a charge for a different amount than the gateway recorded,
- deduct a different processor fee,
- disburse a payout the ledger thinks failed, or fail one the ledger thinks paid,
- report a chargeback or adjustment the ledger hasn't seen.

Reconciliation is the daily process that compares the ledger's view against the
processor's statement and flags any divergence. It is what turns "our books are
internally consistent" into "our books match reality."

## 6. Daily reconciliation

Reconciliation runs once per day (typically shortly after the processor publishes
the prior day's settlement statement). It has two independent checks.

### 6.1 The clearing-account check

`processor_clearing` is an asset representing money in transit from the processor.
Over a **complete, clean cycle** — every settled charge fully allocated, every
payout paid, every processor fee swept — the clearing pool should **net to zero**
for that cycle: money that came in as settlements has fully left as revenue,
processor fees, and payouts.

Trace it for `chg_0001` through a full cycle:

```
settlement (jrnl_stl_0001):  DEBIT  processor_clearing  12000
                             CREDIT processor_fees        205   (processor keeps its cut)
                             CREDIT platform_revenue       348
                             CREDIT seller_payable        11447
payout    (jrnl_pay_0001):   CREDIT processor_clearing   11447   (seller net leaves)
                             DEBIT  seller_payable        11447

processor_clearing net = +12000 − 11447 = +553
```

The residual `+553` is exactly `platform_revenue (348) + processor_fees (205)` —
the money that has *not yet* physically left the clearing pool because the
platform's revenue sweep and the processor's fee retention settle on their own
cadence. When those sweeps complete (revenue transferred to the platform's
account, processor fee retained by the processor), the clearing pool for this
charge reaches zero. **The reconciliation target is: after all sweeps for the
period, `processor_clearing` nets to zero.** A persistent non-zero clearing
balance after sweeps is a discrepancy (§6.3).

### 6.2 The line-by-line processor match

The second check matches the ledger's movements against the processor's
statement, item by item, using `processor_ref` as the join key:

1. Pull the processor's settlement statement for the day (list of settled
   charges with amounts and fees, each with a `processor_ref`).
2. Pull the ledger's settlement entries for the day (each carries the
   `charge.processor_ref`).
3. Join on `processor_ref` and compare `amount` and `processor_fee`. Any
   mismatch, any processor item with no ledger entry (missing settlement), and
   any ledger entry with no processor item (phantom settlement) is a discrepancy.
4. Repeat for payouts: match the processor's disbursement report against ledger
   payout entries on `processor_ref` (the value from `payout.paid`). Confirm
   every `paid` batch has a matching processor disbursement, and every processor
   disbursement has a `paid` batch.
5. Repeat for refunds: match processor refund records against ledger reversal
   entries.

Because the ledger derives balances from immutable entries
([05 — Ledger Model and Invariants §7](05-ledger-model-and-invariants.md#7-how-balances-are-derived)),
the reconciliation job can also fully replay the journal and confirm the snapshot
checkpoints match a from-zero fold — a self-check that the balance-derivation
optimization hasn't drifted.

### 6.3 Discrepancy handling

Discrepancies are never fixed by editing history — the journal is immutable
([ADR-005](10-architecture-decision-records.md#adr-005-immutable-journal-with-reversal-entries)).
They are resolved by posting **new** entries:

| Discrepancy | Resolution |
| ----------- | ---------- |
| Processor settled a **different amount** than recorded | Post a correcting entry (a reversal of the wrong portion plus a corrected settlement) so the ledger matches the processor. Investigate root cause in gateway `pricing`/`processor`. |
| Processor **fee differs** from recorded `processor_fee` | Post an adjusting entry moving the delta between `processor_fees` and `processor_clearing`. |
| Payout **paid at processor** but ledger shows `processing`/`failed` | Reconcile the batch to `paid`, post the missing `jrnl_pay_*` entry debiting `seller_payable`. This is the "resolve in-doubt payout" case from §4.2. |
| Payout **failed at processor** but ledger shows `paid` | Post a reversing entry re-crediting `seller_payable` and re-establishing `processor_clearing`; set the batch `failed`; re-schedule. |
| Chargeback / adjustment the ledger hasn't seen | Post the appropriate dispute entry (moves funds via `platform_reserve:{platform_id}` per dispute policy). |

Every discrepancy is logged to the audit log (see
[09 — Security and Compliance §audit-log](09-security-and-compliance.md#audit-log))
with the `processor_ref`, the expected and actual amounts, and the id of the
correcting entry, so the resolution itself is auditable.

## 7. Runbook

Operational procedures for the on-call engineer. All monetary values in minor
units; all times RFC-3339 UTC.

### 7.1 A batch is stuck in `processing`

Symptom: a `PayoutBatch` has been `processing` beyond the expected window (retries
exhausted without a definitive result).

1. **Do not** manually re-trigger `POST /v1/payouts` blindly — check first whether
   the money already moved.
2. Query the processor for a disbursement matching the batch id / seller / amount
   (the payout used the batch id as idempotency key, so at most one disbursement
   exists).
3. **If the processor shows a successful disbursement:** the `payout.paid` event
   was lost. Re-drive it — replay the event to the ledger via `POST
   /internal/events` (idempotent on `event.id`, safe). The batch moves to `paid`
   and `jrnl_pay_*` posts. Confirm `seller_payable` dropped by the amount.
4. **If the processor shows no disbursement:** the payout never executed. It is
   safe to re-execute (the idempotency guard prevents a double-pay if it *had*
   partially executed). Re-issue `POST /v1/payouts` for the batch.
5. **If the processor state is ambiguous:** leave the batch `processing`, open an
   incident, and resolve during the next reconciliation window (§6.3) rather than
   guessing. Never post a payout entry on a guess.

### 7.2 A batch is `failed`

1. Read the failure reason surfaced on the console Payouts screen.
2. Confirm via reconciliation that **no** money moved (no processor disbursement
   for the batch id) — the ledger should have posted no `jrnl_pay_*` entry and
   `seller_payable` should be intact.
3. Fix the root cause (e.g. update the seller's bank details / KYC), then build a
   fresh batch with `POST /v1/payout-batches`. Do not reuse the failed batch id.

### 7.3 Reconciliation reports a clearing discrepancy

1. Confirm all sweeps for the period have completed (revenue transfer, processor
   fee retention). A non-zero clearing balance *before* sweeps complete is
   expected (§6.1), not a discrepancy.
2. If clearing is non-zero *after* sweeps, run the line-by-line match (§6.2) to
   localize which charge, payout, or refund is off.
3. Post the appropriate correcting entry (§6.3). Never edit existing entries.
4. Log the discrepancy and its resolution to the audit log.

### 7.4 Daily reconciliation checklist

- [ ] Processor settlement statement pulled for the day.
- [ ] Processor disbursement report pulled for the day.
- [ ] Line-by-line settlement match on `processor_ref` — zero unmatched.
- [ ] Line-by-line payout match on `processor_ref` — zero unmatched.
- [ ] Refund match — zero unmatched.
- [ ] `processor_clearing` nets to zero after all sweeps.
- [ ] Journal full-replay matches snapshot checkpoints.
- [ ] Any discrepancy has a correcting entry id and an audit-log record.

If every box is checked, the ledger and the processor agree to the cent for the
day, and the books are certified. If any box fails, an incident is opened and the
relevant runbook section above is followed before the day is certified.
