# Money Movement and Fees

> Audience: engineers in `obol-gateway` (which *computes* fees) and
> `obol-ledger` (which *records* them), plus anyone reconciling a specific
> charge. This document is the definitive reference for how a buyer payment
> splits into platform fee, processor fee, and seller net; the basis-points fee
> formula and its banker's-rounding rule; the exact ledger postings for a
> settlement and a refund give-back; a fully worked example for `chg_0001`; and
> the currency-handling rules.
>
> Companion reading: the double-entry structure and account definitions are in
> [05 — Ledger Model and Invariants](05-ledger-model-and-invariants.md); the
> events that carry these amounts between repos are in
> [07 — Event Catalog](07-event-catalog.md). Design rationale is in
> [10 — Architecture Decision Records](10-architecture-decision-records.md).

## 1. The split, in one picture

A buyer pays a charge amount `A`. That money is split three ways:

```
        buyer pays A
            │
            ▼
   ┌─────────────────────┐
   │  charge amount  A    │   e.g. €120.00
   └─────────────────────┘
      │        │        │
      ▼        ▼        ▼
 platform   processor  seller net
   fee P      fee F       N
  (Obol's    (card       (what the
  customer   network's   seller
  revenue)   cut)        receives)

   N = A − P − F
```

- **`A` (charge amount):** what the buyer is charged. Set by the platform on the
  order. Represented as `Money`.
- **`P` (platform fee):** Obol's / the platform's revenue on the sale, computed
  from a basis-points rate (§2). Recorded to `platform_revenue`.
- **`F` (processor fee):** the card processor's fee, quoted by the processor
  adapter per charge. Recorded to `processor_fees`.
- **`N` (seller net):** the remainder, `N = A − P − F`. This is what accrues to
  `seller_payable:{seller_id}` and is eventually paid out.

The three destination amounts always sum back to the charge amount:
`P + F + N = A`. There is no rounding slack: `N` is computed as the exact integer
remainder `A − P − F`, so the split is *exhaustive* by construction. Every minor
unit of `A` lands in exactly one bucket.

## 2. The basis-points fee formula

The platform fee is a percentage of the charge amount, expressed in **basis
points** (bps). One basis point is 0.01%; a 2.9% fee is `290` bps. The rate for a
charge is the platform's `default_platform_fee_bps` unless overridden per charge.

```
platform_fee_minor = round_half_even( amount_minor * platform_fee_bps / 10000 )
```

All arithmetic is on integers in minor units until the single division, which is
where rounding happens. The division by `10000` comes from bps being hundredths
of a percent: `amount * (bps/10000)` where `bps/10000` is the fractional rate
(e.g. `290/10000 = 0.029`).

### 2.1 Banker's rounding (round half to even)

The rounding mode is **round half to even**, also called banker's rounding. When
the exact result is not an integer, round to the nearest integer; when it is
exactly halfway between two integers, round to the *even* one.

Why banker's rounding rather than round-half-up:
[ADR-006](10-architecture-decision-records.md#adr-006-basis-points-fees-with-bankers-rounding)
records the full reasoning. In short, round-half-up is biased — it always pushes
half-way cases upward, so across millions of charges the platform systematically
over-collects fees by a fraction of a cent per rounded charge. Round-half-to-even
has no directional bias: halves go up half the time and down half the time, so
the expected rounding error is zero. For a company reconciling to the cent
against a processor, an unbiased rule keeps the books honest and keeps the
computed fee matching an independent recomputation.

Worked rounding cases (rate 290 bps, so multiply by 0.029):

| `amount_minor` | exact `amount*290/10000` | rounded (half-even) | note |
| -------------- | ------------------------ | ------------------- | ---- |
| 12000          | 348.0                    | 348                 | exact, no rounding |
| 5000           | 145.0                    | 145                 | exact |
| 1724           | 49.996                   | 50                  | nearest is up |
| 1725           | 50.025                   | 50                  | nearest is down |
| 1000           | 29.0                     | 29                  | exact |
| 50             | 1.45                     | 1                   | nearest is down |
| 250            | 7.25                     | 7                   | not a half; nearest down |

A true half-way case: at 500 bps (5%) on `amount_minor = 90`, the exact result is
`90 * 500 / 10000 = 4.5`. Round-half-even → `4` (even). At `amount_minor = 110`,
`110 * 500 / 10000 = 5.5` → `6` (even). Two adjacent halves, one rounds down and
one rounds up — that symmetry is the point.

### 2.2 Where the computation lives

Fee computation is the responsibility of `obol-gateway`, in the `pricing`
package. The gateway computes `platform_fee` (and reads `processor_fee` from the
processor adapter) *before* it emits any event. The ledger never recomputes the
fee; it records the amounts carried on the `payment.settled` event exactly as
received. This is the "computed vs recorded" split called out in the spec's
cross-repo relationships: gateway `pricing` computes, ledger `posting` records.
See [ADR-002](10-architecture-decision-records.md#adr-002-money-as-integer-minor-units)
for why every amount is an integer minor-unit value throughout.

The processor fee `F` is **not** derived from a bps rate that Obol owns — it is
quoted by the processor per transaction and returned by the `processor` adapter
when the charge is authorized/settled. Obol records whatever the processor
charged. In the deterministic mock processor used for tests, `F` for `chg_0001`
is `{ 205, "EUR" }`.

## 3. The settlement posting

When a charge settles, the gateway emits `payment.settled` carrying `amount`,
`platform_fee`, and `processor_fee`. The ledger consumes it and posts the
settlement entry. Using amount `A`, platform fee `P`, processor fee `F`, and
seller net `N = A − P − F`:

```
DEBIT  processor_clearing            A     # cleared funds arrive as an asset
CREDIT platform_revenue              P     # platform fee becomes revenue
CREDIT processor_fees (contra)       F     # processor's cut, offsets clearing
CREDIT seller_payable:{seller}       N     # remainder owed to the seller
```

This balances by construction: `debits = A` and
`credits = P + F + N = P + F + (A − P − F) = A`. The invariant
`sum(debits) == sum(credits)` from
[05 — Ledger Model and Invariants](05-ledger-model-and-invariants.md#5-the-balance-invariant)
holds for *any* valid split, which is why the exhaustive-remainder definition of
`N` matters: if `N` were rounded independently, the entry could fail to balance.

## 4. The refund give-back

A refund reverses all or part of a charge. Refunds never mutate the original
settlement entry; the ledger posts a new, opposite entry — see the immutability
rule in
[05 — Ledger Model and Invariants](05-ledger-model-and-invariants.md#6-immutability-refunds-post-reversals-never-mutations).

For a refund of amount `R` against a charge with amount `A`, the fees are given
back *proportionally* to the refunded fraction `R / A`, using banker's rounding
on each fee give-back:

```
refund_fraction        = R / A                       # conceptual; not stored as float
platform_fee_giveback  = round_half_even( P * R / A )
processor_fee_giveback  = round_half_even( F * R / A )
seller_clawback        = R − platform_fee_giveback − processor_fee_giveback
```

The reversal entry (mirror image of settlement) is:

```
DEBIT  seller_payable:{seller}       seller_clawback         # reduce what we owe the seller
DEBIT  platform_revenue              platform_fee_giveback   # give back platform revenue
DEBIT  processor_fees                processor_fee_giveback  # reverse the processor cut
CREDIT processor_clearing            R                       # R leaves clearing back to buyer
```

Balance check: `debits = seller_clawback + platform_fee_giveback +
processor_fee_giveback = R` (because `seller_clawback` is defined as the exact
remainder), and `credits = R`. Balanced for any `R ≤ A`.

### 4.1 Full refund

A full refund is the special case `R = A`. Then `R / A = 1`, so every give-back
equals the original fee and the reversal is the exact mirror of the settlement.
For `chg_0001` (`A = 12000`, `P = 348`, `F = 205`, `N = 11447`):

```
platform_fee_giveback  = round_half_even( 348 * 12000 / 12000 ) = 348
processor_fee_giveback  = round_half_even( 205 * 12000 / 12000 ) = 205
seller_clawback        = 12000 − 348 − 205 = 11447
```

The full-refund reversal is worked end to end, including the invariant check and
the return-to-zero balance table, in
[05 — Ledger Model and Invariants §9](05-ledger-model-and-invariants.md#9-worked-example--full-refund-reversal-of-chg_0001).

### 4.2 Partial refund (worked)

Suppose the buyer is refunded €40.00 of `chg_0001` — `R = { 4000, "EUR" }`
against `A = 12000`, so the refunded fraction is `4000 / 12000 = 1/3`.

```
platform_fee_giveback  = round_half_even( 348 * 4000 / 12000 )
                       = round_half_even( 1392000 / 12000 )
                       = round_half_even( 116.0 ) = 116     # €1.16

processor_fee_giveback  = round_half_even( 205 * 4000 / 12000 )
                       = round_half_even( 820000 / 12000 )
                       = round_half_even( 68.333… ) = 68     # €0.68

seller_clawback        = 4000 − 116 − 68 = 3816             # €38.16
```

Reversal entry:

```
JournalEntry jrnl_rev_0001p  (kind=refund_reversal, currency=EUR)

  DEBIT  seller_payable:sell_atelier    3816    # €38.16 clawed back
  DEBIT  platform_revenue                116    # €1.16 platform fee given back
  DEBIT  processor_fees                   68    # €0.68 processor fee reversed
  CREDIT processor_clearing             4000    # €40.00 returned to the buyer
```

Balance check: `debits = 3816 + 116 + 68 = 4000`, `credits = 4000`. ✓

After this partial refund, the charge's residual balances (settlement from §5
minus this reversal) are:

| Account                       | After settlement | After €40 refund | Residual |
| ----------------------------- | ---------------- | ---------------- | -------- |
| `processor_clearing`          | +12000           | −4000            | +8000    |
| `platform_revenue`            | +348             | −116             | +232     |
| `processor_fees`              | +205             | −68              | +137     |
| `seller_payable:sell_atelier` | +11447           | −3816            | +7631    |

The residual clearing (8000) still equals residual revenue (232) + residual
expense (137) + residual seller payable (7631): `232 + 137 + 7631 = 8000`. The
split stays exhaustive after the partial refund — the seller now nets €76.31 on
the €80.00 of the sale that was kept, and the platform keeps €2.32 of fee. The
charge status becomes `partially_refunded` (see the `Charge` entity in the spec).

## 5. Fully worked example — `chg_0001` settlement

Bringing the whole settlement path together with the fixed sample data.

**Inputs (from the spec's fixed sample data):**

- Charge `chg_0001`, platform `plat_marisqueira`
  (`default_platform_fee_bps = 290`), seller `sell_atelier`.
- `amount = { 12000, "EUR" }` — €120.00.

**Step 1 — compute the platform fee (gateway `pricing`):**

```
platform_fee_minor = round_half_even( 12000 * 290 / 10000 )
                   = round_half_even( 3480000 / 10000 )
                   = round_half_even( 348.0 )
                   = 348                                  # €3.48
```

Because `348.0` is exact, banker's rounding is a no-op here — a clean case, which
is why it's the canonical sample.

**Step 2 — read the processor fee (gateway `processor` adapter):**

```
processor_fee = { 205, "EUR" }                            # €2.05, quoted by processor
```

**Step 3 — compute seller net (exact remainder):**

```
seller_net_minor = 12000 − 348 − 205 = 11447              # €114.47
```

**Step 4 — the gateway emits `payment.settled`** carrying these amounts (see the
event's exact `data` schema and JSON example in
[07 — Event Catalog](07-event-catalog.md#paymentsettled)):

```json
{
  "id": "evt_settled_0001",
  "type": "payment.settled",
  "ts": "2026-09-15T10:32:04Z",
  "data": {
    "charge_id": "chg_0001",
    "platform_id": "plat_marisqueira",
    "seller_id": "sell_atelier",
    "amount":        { "amount_minor": 12000, "currency": "EUR" },
    "platform_fee":  { "amount_minor": 348,   "currency": "EUR" },
    "processor_fee": { "amount_minor": 205,   "currency": "EUR" }
  }
}
```

**Step 5 — the ledger posts the settlement entry** (from §3, substituting
`A=12000, P=348, F=205, N=11447`):

```
JournalEntry jrnl_stl_0001  (kind=settlement, currency=EUR,
                             event_id=evt_settled_0001)

  DEBIT  processor_clearing              12000
  CREDIT platform_revenue                  348
  CREDIT processor_fees                     205
  CREDIT seller_payable:sell_atelier     11447
```

**Reconciliation of the numbers:**

```
platform_fee  P = 348      (€3.48,  290 bps on €120.00)
processor_fee F = 205      (€2.05)
seller_net    N = 11447    (€114.47)
sum P+F+N       = 348 + 205 + 11447 = 12000 = A   ✓ exhaustive
debits          = 12000
credits         = 348 + 205 + 11447 = 12000       ✓ balances
```

Every number here matches the fixed sample data in the spec exactly, and matches
the worked settlement in
[05 — Ledger Model and Invariants §8](05-ledger-model-and-invariants.md#8-worked-example--settlement-of-chg_0001).
This is the reference example the whole test dataset is calibrated against.

## 6. Currency handling rules

Obol's money rules are strict and identical in every repo. See the spec's Money
section; this is the operational restatement.

1. **Every amount is `Money = { amount_minor: int64, currency: string }`.** Minor
   units (cents for EUR), integer, never a float. €120.00 is `{ 12000, "EUR" }`,
   not `120.0`. Rationale in
   [ADR-002](10-architecture-decision-records.md#adr-002-money-as-integer-minor-units).

2. **Arithmetic is only allowed between same-currency `Money`.** Adding a EUR
   amount to a USD amount is a programming error and is rejected at the boundary,
   not silently coerced. The `pricing` and `posting` code assert matching
   currency before any add/subtract.

3. **A `JournalEntry` is single-currency.** All lines in an entry share the
   entry's `currency`. There is no mixed-currency entry (see
   [05 — Ledger Model and Invariants §4](05-ledger-model-and-invariants.md#4-journalentry-and-journalline)).

4. **A seller has one `payout_currency`.** Both sample sellers, `sell_atelier`
   and `sell_ceramica`, are EUR. A seller's `seller_payable` account accrues in
   that currency, and payouts are made in it.

5. **The fee rate is currency-agnostic; the amounts are not.** `290` bps means
   2.9% regardless of currency, but `platform_fee` is computed in the charge's
   currency and stays in that currency all the way to `platform_revenue`.

6. **No implicit FX.** Obol does not convert currencies inside a charge, a
   settlement, or a refund. If a platform ever needs cross-currency movement, it
   is modeled as explicit paired entries through an FX account — never as a
   silent conversion inside an existing entry. In the current sample dataset
   (EUR sellers, PT platform) no FX occurs at all.

7. **Rounding happens exactly once per fee, at the division.** All other
   arithmetic (the seller-net remainder, the sum-back check) is exact integer
   arithmetic with no rounding, which is what keeps `P + F + N == A` a hard
   equality rather than an approximation.

## 7. Quick reference

| Quantity | Symbol | Formula | `chg_0001` value |
| -------- | ------ | ------- | ---------------- |
| Charge amount | `A` | given | 12000 (€120.00) |
| Platform fee | `P` | `round_half_even(A * bps / 10000)` | 348 (€3.48) |
| Processor fee | `F` | quoted by processor | 205 (€2.05) |
| Seller net | `N` | `A − P − F` (exact) | 11447 (€114.47) |
| Fee rate | `bps` | platform default or override | 290 (2.9%) |
| Refund giveback (fee) | — | `round_half_even(fee * R / A)` | full: same as `P`,`F` |
| Seller clawback | — | `R − sum(fee givebacks)` | full: 11447 |

If a computed value here ever disagrees with the ledger, the ledger's recorded
amounts win for *what happened*, and this document plus the spec win for *what
should have happened* — a disagreement between them is a bug to be reconciled,
per [08 — Payouts and Reconciliation](08-payouts-and-reconciliation.md).
