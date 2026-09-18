# The Ledger Model and Its Invariants

> Audience: engineers working in `obol-ledger`, and anyone who needs to reason
> about where Obol's money is at any instant. This document explains the
> double-entry model in depth: why we use it, the chart of accounts, the
> `JournalEntry` / `JournalLine` structures, the balance invariant and how it is
> enforced, journal immutability, how balances are derived, and worked examples
> tied to the fixed sample data.
>
> Companion reading: money-movement mechanics and the fee formula live in
> [06 — Money Movement and Fees](06-money-movement-and-fees.md); the events that
> trigger postings are catalogued in [07 — Event Catalog](07-event-catalog.md);
> payout construction and reconciliation are in
> [08 — Payouts and Reconciliation](08-payouts-and-reconciliation.md). The
> rationale behind several of the choices here is recorded as ADRs in
> [10 — Architecture Decision Records](10-architecture-decision-records.md).

## 1. Why double-entry

Obol moves other people's money. At every moment we must be able to answer three
questions with certainty and with an audit trail:

1. How much do we owe each seller?
2. How much revenue has the platform earned?
3. Is the money we think we're holding actually accounted for, cent for cent?

A naive design keeps a single mutable `balance` integer per seller and adds to
or subtracts from it as charges and refunds happen. That design is cheap and
almost always wrong in practice. A dropped update, a double-applied refund, a
partial write, or a race between two workers silently corrupts the number, and
there is no way to detect it after the fact because nothing else has to agree
with it. Single-entry balances have no built-in contradiction to trip on.

Double-entry accounting fixes this by making every movement touch **at least two
accounts** such that the total debited always equals the total credited. The sum
of every debit ever recorded equals the sum of every credit ever recorded — a
global invariant that must hold after every single posting. If a bug ever makes
the books not balance, the invariant catches it at write time, before the bad
data can be read. Balances are then *derived* from the immutable log of
movements rather than stored and mutated, so there is no primary number to
corrupt. This is the reasoning captured in
[ADR-001](10-architecture-decision-records.md#adr-001-double-entry-ledger-over-single-entry-balances).

The trade is more rows written per movement and a small amount of accounting
discipline. For a company whose entire product is "keep track of money
correctly," that trade is not close.

## 2. Accounting sign conventions

Obol uses standard double-entry conventions. Each account has a *normal side*,
and whether a debit or a credit increases the account depends on the account
type:

| Account type | Normal balance | Increased by | Decreased by |
| ------------ | -------------- | ------------ | ------------ |
| Asset        | Debit          | Debit        | Credit       |
| Liability    | Credit         | Credit       | Debit        |
| Revenue      | Credit         | Credit       | Debit        |
| Expense      | Debit          | Debit        | Credit       |

Two consequences matter constantly:

- **`seller_payable:{id}` is a liability.** It represents money Obol *owes* a
  seller. It goes *up* with a credit and *down* with a debit. A settlement
  credits it (we now owe the seller more); a payout debits it (we've discharged
  part of what we owed).
- **`processor_clearing` is an asset.** It represents money in transit to us
  from the card network. It goes *up* with a debit when a charge settles and
  *down* with a credit when that money is disbursed (as fees, seller net, or
  payouts leave the clearing pool).

If you ever find yourself unsure which side a movement goes on, return to this
table and ask "is this account going up or down, and what type is it?"

## 3. Chart of accounts

Obol runs a deliberately small chart of accounts. There are exactly five account
*kinds*; two of them are parameterized per seller or per platform, so the number
of concrete accounts grows with the customer base, but the shape never changes.

| Account id pattern             | Type      | Meaning |
| ------------------------------ | --------- | ------- |
| `processor_clearing`           | Asset     | Money in transit from the card processor. A single global clearing pool. Debited when charges settle, credited as that money is allocated out to revenue, fees, and seller payables, and later credited again when payouts leave. Over a full clean cycle it nets toward zero (see §8 and [08 — Payouts and Reconciliation](08-payouts-and-reconciliation.md)). |
| `platform_revenue`             | Revenue   | Accumulated platform fees Obol has earned on behalf of / from the platform. Credited on settlement, debited on refund give-back. |
| `processor_fees`               | Expense   | Fees paid to the card processor. Modeled as a contra-credit against the clearing pool on settlement — the processor keeps its cut, so that portion of the cleared money never becomes ours to disburse. |
| `seller_payable:{seller_id}`   | Liability | What Obol owes a specific seller. Credited (net of fees) on settlement, debited on refund give-back and on payout. One account per seller, e.g. `seller_payable:sell_atelier`. |
| `platform_reserve:{platform_id}` | Liability | Held funds / risk reserve retained against a platform for chargebacks and negative-balance risk. Credited when reserve is withheld, debited when reserve is released. One account per platform, e.g. `platform_reserve:plat_marisqueira`. |

Notes on the parameterized accounts:

- `seller_payable:sell_atelier` and `seller_payable:sell_ceramica` are *distinct
  accounts*. There is no shared "sellers payable" pool; each seller's liability
  is tracked separately so a payout to one seller can never accidentally draw
  down another's balance.
- `platform_reserve:plat_marisqueira` exists per platform. Reserve postings are
  not exercised by the core settlement/refund path in the worked examples below,
  but the account is part of the chart because disputes
  (see the `Dispute` entity in the spec) and risk holds move money here.

Account ids are stable strings. The ledger never renames or deletes an account;
a seller who has churned still has a `seller_payable` account with whatever
history it accumulated.

## 4. JournalEntry and JournalLine

A **`JournalEntry`** is the atomic unit of the ledger. It records one economic
event — a settlement, a refund reversal, a payout — as a set of balanced line
items. An entry is never partially written: either all of its lines commit or
none do.

```
JournalEntry {
  id:            string     # "jrnl_..." prefixed snake id
  event_id:      string     # the event.id that caused this entry (idempotency key)
  kind:          string     # "settlement" | "refund_reversal" | "payout" | ...
  currency:      string     # ISO-4217; all lines in an entry share one currency
  created_at:    string     # RFC-3339 UTC
  lines:         JournalLine[]   # 2 or more, must balance
}
```

A **`JournalLine`** is a single debit or credit against one account:

```
JournalLine {
  account_id:  string   # e.g. "processor_clearing", "seller_payable:sell_atelier"
  side:        string   # "debit" | "credit"
  amount:      Money     # { amount_minor: int64, currency: string }
}
```

Invariants on the structure itself:

- Every line's `amount.currency` equals the entry's `currency`. Obol never mixes
  currencies inside one entry. Cross-currency movements, if they ever exist, are
  modeled as two entries plus an FX account, never as a mixed-currency entry.
- `amount.amount_minor` is a non-negative integer in minor units. Direction is
  carried by `side`, not by sign. There are no negative amounts; a "negative"
  movement is a debit on the opposite side.
- An entry has **2 or more** lines. Most entries have exactly the number the
  posting rule specifies (four for a settlement, three for the standard refund
  reversal).

The `event_id` field is what makes postings idempotent. The event that triggers
a posting carries a unique `id` (see [07 — Event Catalog](07-event-catalog.md)),
and the ledger records that id on the resulting entry. Re-delivering the same
event finds the existing entry and posts nothing new. This is why consumers can
be at-least-once and the books still stay correct — see
[ADR-004](10-architecture-decision-records.md#adr-004-event-driven-ledger-vs-synchronous-posting).

## 5. The balance invariant

The single most important rule in the entire system:

> **For every `JournalEntry`, the sum of debit amounts equals the sum of credit
> amounts, in the same currency.**

Formally, for entry `e`:

```
sum( line.amount.amount_minor for line in e.lines if line.side == "debit" )
  == sum( line.amount.amount_minor for line in e.lines if line.side == "credit" )
```

Because every entry balances, the *global* ledger balances too: the total of all
debits ever posted equals the total of all credits ever posted. That global
identity is the property we lean on during reconciliation
([08 — Payouts and Reconciliation](08-payouts-and-reconciliation.md)).

### 5.1 Where it is enforced

The invariant is checked in the ledger `posting` module at the moment an entry is
constructed, before it is persisted. The posting code builds the list of lines,
then validates:

1. All lines share the entry currency.
2. All amounts are non-negative integers.
3. `sum(debits) == sum(credits)`.

If any check fails, the posting raises and the transaction rolls back. Nothing is
written. A failed invariant is treated as a hard bug — it means a posting rule
produced an unbalanced entry — and it pages the on-call engineer rather than
being swallowed. The check is cheap (a couple of integer sums over a handful of
lines) and runs on the write path unconditionally; there is no "fast path" that
skips it.

Enforcement at write time is the whole point. A validation that only ran nightly
would let unbalanced data be read for hours. Because we validate before commit,
an unbalanced entry can never be observed by any reader.

### 5.2 What the invariant does *not* guarantee

Balancing debits and credits guarantees the books are *internally consistent*. It
does **not** guarantee they match the outside world — the processor could have
settled a different amount than we recorded. Catching that class of error is the
job of reconciliation against the processor, covered in
[08 — Payouts and Reconciliation](08-payouts-and-reconciliation.md). Keep the two
ideas distinct: the invariant is "the ledger agrees with itself"; reconciliation
is "the ledger agrees with the processor."

## 6. Immutability: refunds post reversals, never mutations

Journal entries are **append-only**. Once an entry is committed it is never
updated and never deleted. This is a deliberate design choice
([ADR-005](10-architecture-decision-records.md#adr-005-immutable-journal-with-reversal-entries)).

Consequences:

- **A refund does not touch the original settlement entry.** When
  `refund.completed` arrives, the ledger posts a *new* entry — a
  `refund_reversal` — whose lines are the mirror image of the amounts being
  given back. The original settlement remains exactly as it was posted. The
  charge's economic history is the *sum* of its entries, not the latest state of
  a single mutable record.
- **Corrections are also reversals.** If a posting was wrong, we never edit it.
  We post a compensating reversal that cancels it, then post the correct entry.
  The audit trail shows the mistake and the fix, which is exactly what an auditor
  wants to see.
- **Balances are always derivable and always reproducible.** Because entries
  never change, replaying the journal from the beginning always yields the same
  balances. There is no hidden mutable state that could drift.

Immutability is what lets the ledger be an *audit source of truth* rather than
just a cache of the current numbers. See the audit-log discussion in
[09 — Security and Compliance](09-security-and-compliance.md#audit-log) for how
this ledger property dovetails with tamper-evident logging.

## 7. How balances are derived

There is no stored `balance` column that the system mutates. A balance is a
*query* over journal lines. For an account `A`:

```
balance(A) = sum( line.amount.amount_minor
                  for line in all lines where line.account_id == A
                  with sign(+1) for the account's normal side
                  and sign(-1) for the opposite side )
```

Concretely, using the sign conventions from §2:

- For an **asset** (`processor_clearing`): `debits − credits`.
- For a **liability** (`seller_payable:{id}`, `platform_reserve:{id}`):
  `credits − debits`.
- For **revenue** (`platform_revenue`): `credits − debits`.
- For an **expense** (`processor_fees`): `debits − credits`.

This derivation lives in the ledger `balances` module and backs the
`GET /v1/accounts/{account_id}/balance` endpoint. A statement
(`GET /v1/accounts/{account_id}/statement`) is the same idea without the
collapse: it returns the ordered list of lines touching the account, each with
its entry id and running balance, so a reader can see exactly how the current
number was reached.

Performance note: deriving a balance by scanning all of history would get slow.
The `balances` module keeps periodic **snapshot checkpoints** (a
materialized balance as of a given journal position) and derives the live balance
as `snapshot + sum(lines since the snapshot)`. The snapshot is an optimization
only — it is always exactly reproducible by replaying lines from zero, and it is
validated against a full replay during nightly reconciliation. The *definition*
of a balance remains "a fold over immutable lines."

## 8. Worked example — settlement of `chg_0001`

We now post the fixed sample charge. From the spec's fixed sample data:

- Charge `chg_0001`, seller `sell_atelier`, platform `plat_marisqueira`.
- Amount `A = { 12000, "EUR" }` — €120.00.
- Platform fee `P = { 348, "EUR" }` — €3.48 (290 bps on €120.00; see
  [06 — Money Movement and Fees](06-money-movement-and-fees.md) for the
  banker's-rounding derivation).
- Processor fee `F = { 205, "EUR" }` — €2.05.
- Seller net `N = A − P − F = 12000 − 348 − 205 = 11447` — €114.47.

When `payment.settled` for `chg_0001` is consumed, the ledger `posting` module
builds this entry:

```
JournalEntry jrnl_stl_0001  (kind=settlement, currency=EUR,
                             event_id=evt_settled_0001)

  DEBIT  processor_clearing              12000    # €120.00 arrives in clearing
  CREDIT platform_revenue                  348    # €3.48 platform fee earned
  CREDIT processor_fees                     205    # €2.05 processor cut (contra)
  CREDIT seller_payable:sell_atelier     11447    # €114.47 now owed to the seller
```

Invariant check:

```
debits  = 12000
credits = 348 + 205 + 11447 = 12000
12000 == 12000   ✓  balances
```

Resulting balances after this single entry (all EUR, in minor units):

| Account                         | Type      | Formula        | Balance |
| ------------------------------- | --------- | -------------- | ------- |
| `processor_clearing`            | Asset     | debits−credits | +12000  |
| `platform_revenue`              | Revenue   | credits−debits | +348    |
| `processor_fees`                | Expense   | debits−credits | +205    |
| `seller_payable:sell_atelier`   | Liability | credits−debits | +11447  |

Read this as: Obol is holding €120.00 in clearing, has earned €3.48 of revenue,
has incurred €2.05 of processor expense, and owes Atelier Costa €114.47. The
clearing asset (12000) equals revenue (348) + expense (205) + seller payable
(11447) — the money has been fully allocated but not yet disbursed.

When Atelier Costa is later paid out (see §9 and
[08 — Payouts and Reconciliation](08-payouts-and-reconciliation.md)), the €114.47
leaves `seller_payable:sell_atelier` and `processor_clearing`, driving both down.
After payout, and after the processor's fee sweep, the clearing pool for this
charge nets to zero — which is precisely the reconciliation target in §5.2.

## 9. Worked example — full refund reversal of `chg_0001`

Suppose the buyer is fully refunded. A `Refund` of `R = { 12000, "EUR" }` against
`chg_0001` completes, emitting `refund.completed`. Obol's policy for a full
refund is to give the buyer back the entire €120.00 and to *reverse the platform
fee* — the platform does not keep revenue on a fully refunded sale. The processor
fee behavior follows Obol's processor terms; in the sample model the processor
fee give-back on a full refund is proportional and, for a full refund, complete.

The mirror-image entry per the spec debits `seller_payable` and
`platform_revenue` and credits `processor_clearing`. For a *full* refund of
`chg_0001`, the proportional fee give-back returns the whole platform fee and the
whole processor fee, so the reversal is the exact mirror of the settlement:

```
JournalEntry jrnl_rev_0001  (kind=refund_reversal, currency=EUR,
                             event_id=evt_refund_0001)

  DEBIT  seller_payable:sell_atelier     11447    # claw back the €114.47 we owed
  DEBIT  platform_revenue                  348    # give back the €3.48 platform fee
  DEBIT  processor_fees                     205    # reverse the €2.05 processor cut
  CREDIT processor_clearing              12000    # €120.00 leaves clearing to the buyer
```

Invariant check:

```
debits  = 11447 + 348 + 205 = 12000
credits = 12000
12000 == 12000   ✓  balances
```

Net effect on balances, combining the settlement entry (§8) and this reversal:

| Account                         | After settlement | After reversal | Net    |
| ------------------------------- | ---------------- | -------------- | ------ |
| `processor_clearing`            | +12000           | −12000         | 0      |
| `platform_revenue`              | +348             | −348           | 0      |
| `processor_fees`                | +205             | −205           | 0      |
| `seller_payable:sell_atelier`   | +11447           | −11447         | 0      |

Every account returns to zero for this charge, which is the correct outcome for a
full refund: no money owed, no revenue kept, no expense retained. Crucially, we
achieved this **without mutating** `jrnl_stl_0001`. The charge's history now
shows two entries — the settlement and its reversal — and their sum is zero. An
auditor can see both the original sale and its unwinding.

For a **partial** refund, the same shape applies but with the refunded fraction
of each amount, computed with banker's rounding on the fee give-back. The
detailed partial-refund arithmetic is worked in
[06 — Money Movement and Fees](06-money-movement-and-fees.md#refund-give-back).

## 10. Invariant checklist (for reviewers and on-call)

When touching anything in the `posting` module, verify:

- [ ] Every new entry has 2+ lines.
- [ ] All lines in an entry share the entry's currency.
- [ ] All `amount_minor` values are non-negative integers (direction via `side`).
- [ ] `sum(debits) == sum(credits)` for the entry — the check runs before commit.
- [ ] The entry carries the triggering `event_id`; re-posting the same event is a
      no-op (idempotency).
- [ ] No existing entry is updated or deleted; corrections are new reversal
      entries.
- [ ] Seller money moves through `seller_payable:{that seller}`, never a shared
      pool.
- [ ] Balances are derived from lines, not read from a mutable field.

If any box can't be checked, the change is not safe to merge. The ledger is the
one place in Obol where "mostly correct" is indistinguishable from "silently
losing customer money."
