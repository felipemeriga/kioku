# Obol — Marketplace Integration Guide

> A step-by-step guide for a marketplace integrating Obol end to end: onboarding
> the platform, onboarding sellers and clearing KYC, taking a charge from a
> buyer order, handling settlement, reading balances, scheduling payouts, and
> handling refunds and disputes. It uses Obol's fixed sample data throughout so
> examples line up with the rest of the docs.
>
> Prerequisites: skim [01-product-overview.md](./01-product-overview.md) for the
> model and [04-gateway-api-reference.md](./04-gateway-api-reference.md) for the
> exact API. Terms are defined in
> [03-domain-glossary.md](./03-domain-glossary.md); the moving parts are in
> [02-system-architecture.md](./02-system-architecture.md).

Sample data used below:

- Platform `plat_marisqueira` — "Marisqueira Marketplace", `PT`,
  `default_platform_fee_bps = 290`.
- Sellers `sell_atelier` ("Atelier Costa", EUR) and `sell_ceramica`
  ("Cerâmica do Vale", EUR).
- Charge `chg_0001` — €120.00 → platform_fee €3.48, processor_fee €2.05,
  seller net €114.47.

Code snippets are illustrative pseudo-JS using an `obol` client that wraps the
REST API; adapt to your language. Money is always
`{ amount_minor, currency }`.

---

## Integration at a glance

```
 1. Onboard the platform         (get API key for plat_marisqueira)
 2. Onboard sellers + KYC        (create sellers, reach kyc_status=verified)
 3. Create a charge              (POST /v1/charges from a buyer order)
 4. Handle settlement           (consume payment.settled; ledger posts entry)
 5. Read seller balances         (GET /v1/accounts/{seller_payable}/balance)
 6. Schedule payouts             (POST /v1/payout-batches → gateway payout)
 7. Handle refunds               (POST /v1/charges/{id}/refunds)
 8. Handle disputes              (track Dispute state open → won|lost)
```

Each step below is self-contained and references the endpoints and events it
uses.

---

## Step 1 — Onboard the platform

Your marketplace is the **platform** — Obol's direct customer. Onboarding
produces your `Platform` record and an API key.

```
Platform {
  id:                       "plat_marisqueira",
  name:                     "Marisqueira Marketplace",
  country:                  "PT",
  default_platform_fee_bps: 290,          // 2.9% commission
  created_at:               "2026-01-04T09:00:00Z"
}
```

The `default_platform_fee_bps` is your commission on every charge, in basis
points (`290` = 2.9%). It drives the fee split the gateway computes.

You receive a secret API key scoped to `plat_marisqueira`:

```js
const obol = new Obol({
  apiKey: process.env.OBOL_API_KEY,     // "sk_live_marisqueira_9f2b..."
  baseUrl: "https://api.obol.example/v1"
});
```

Keep the key server-side. In the → Console, the Express BFF holds it; the React
SPA never sees it. Authentication details are in
[04-gateway-api-reference.md](./04-gateway-api-reference.md#authentication--api-key).

**Checkpoint:** you can authenticate; requests act as `plat_marisqueira`.

---

## Step 2 — Onboard sellers and clear KYC

Every sub-merchant on your marketplace is a **Seller**. Create one per merchant,
with their payout currency. A seller starts at `kyc_status = pending` and cannot
be paid out until they reach `verified`.

```js
const atelier = await obol.sellers.create({
  platform_id:     "plat_marisqueira",
  display_name:    "Atelier Costa",
  payout_currency: "EUR"
});
// => { id: "sell_atelier", kyc_status: "pending", ... }
```

Drive the seller through KYC (identity + bank details). Obol updates
`kyc_status`:

```
   pending ──▶ verified     seller can now be paid out
      └───────▶ rejected    seller cannot be paid out
```

Both sample sellers end up `verified`:

```
sell_atelier   "Atelier Costa"     kyc_status=verified  payout_currency=EUR
sell_ceramica  "Cerâmica do Vale"  kyc_status=verified  payout_currency=EUR
```

**Gate your own flows on this.** Do not attempt a payout for a seller whose
`kyc_status != verified` — the gateway rejects it with `422
seller_not_verified`. It is fine to *accept charges* for a pending seller
(their net simply accrues); only *payout* requires verification.

**Checkpoint:** at least one seller is `verified` with a `payout_currency`.

---

## Step 3 — Create a charge from a buyer order

When a buyer checks out an order, create a **Charge**. You send the seller and
the gross amount; Obol computes the fee split and settles the payment.

`POST /v1/charges` **requires** an `Idempotency-Key` header. Generate one
**per order** and reuse it only if you retry that same order — this is what
guarantees a network retry never double-charges the buyer (the key is checked
before any processor call).

```js
const idemKey = order.id + ":charge";   // stable per order; e.g. a UUID you store

const charge = await obol.charges.create(
  {
    seller_id:      "sell_atelier",
    amount:         { amount_minor: 12000, currency: "EUR" },  // €120.00
    payment_method: buyer.paymentToken                          // "tok_visa_4242"
  },
  { idempotencyKey: idemKey }
);
```

The response is the fully-split, settled charge:

```json
{
  "id": "chg_0001",
  "seller_id": "sell_atelier",
  "amount":        { "amount_minor": 12000, "currency": "EUR" },
  "platform_fee":  { "amount_minor": 348,   "currency": "EUR" },
  "processor_fee": { "amount_minor": 205,   "currency": "EUR" },
  "seller_net":    { "amount_minor": 11447, "currency": "EUR" },
  "status": "settled",
  "idempotency_key": "...:charge",
  "processor_ref": "mockproc_auth_7Ka9",
  "created_at": "2026-09-18T10:15:30Z"
}
```

How the split is derived (you do not compute this — Obol does — but you should
be able to reconcile it):

```
platform_fee = round_half_even(12000 * 290 / 10000) = 348   (€3.48)
processor_fee = 205                                          (€2.05, from processor)
seller_net    = 12000 − 348 − 205 = 11447                    (€114.47)
```

**Idempotency retry pattern:**

```js
async function chargeWithRetry(body, idemKey) {
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      return await obol.charges.create(body, { idempotencyKey: idemKey });
    } catch (e) {
      if (e.status >= 500 || e.code === "rate_limit_error") continue; // safe: same key
      throw e; // 4xx business errors: do not retry blindly
    }
  }
}
```

Because the same `idemKey` is reused, a retry after a timeout returns the
*original* `chg_0001` rather than creating a second charge.

**Checkpoint:** you have a settled `chg_0001` and stored its id against your
order.

---

## Step 4 — Handle settlement

Creating the charge returns `status: "settled"` synchronously, but the
*accounting* happens asynchronously: the gateway emits events and the ledger
posts the journal entry. See the sync-vs-event boundary in
[02-system-architecture.md](./02-system-architecture.md#3-the-synchronous-vs-event-driven-boundary).

Sequence:

```
gateway emits: payment.authorized   (ledger records)
gateway emits: payment.settled      (ledger POSTS the settlement entry)
```

On `payment.settled` the ledger `posting` module writes one balanced
`JournalEntry` for `chg_0001`:

```
DEBIT  processor_clearing              12000
CREDIT platform_revenue                  348
CREDIT processor_fees (contra)           205
CREDIT seller_payable:sell_atelier     11447
                                       ─────
              debits 12000 == credits 12000  ✓
```

**What you should do:**

- If you subscribe to Obol events, make your handler **idempotent on
  `event.id`** — Obol delivers at-least-once, so you may see a duplicate.
- Do not treat money as "in the seller's balance" until settlement; the
  authoritative source is the ledger, not your own counter.

```js
function onObolEvent(evt) {              // evt = { id, type, ts, data }
  if (alreadyProcessed(evt.id)) return;  // idempotent on event.id
  switch (evt.type) {
    case "payment.settled":
      markOrderPaid(evt.data.charge_id); // sell_atelier net now accrued in ledger
      break;
    // ... refund.completed, payout.paid, etc.
  }
  recordProcessed(evt.id);
}
```

**Checkpoint:** the seller's payable balance has grown by the seller net.

---

## Step 5 — Read seller balances

A seller's balance is **derived from the ledger**, not a counter you maintain.
Read it from the ledger by account id. The seller's payable account is
`seller_payable:{seller_id}`.

```js
const balance = await obol.ledger.getBalance("seller_payable:sell_atelier");
// => { account_id: "seller_payable:sell_atelier",
//      balance: { amount_minor: 11447, currency: "EUR" } }
```

After the single sample charge, `sell_atelier` is owed **€114.47**. For the
full history behind it, read the statement:

```js
const statement = await obol.ledger.getStatement("seller_payable:sell_atelier");
// ordered JournalLines: +11447 (settlement of chg_0001), then payout debits, etc.
```

In the → Console, this is exactly what the **Balances** screen shows: the
`BalancePage` → BFF `balances` route → ledger
`GET /v1/accounts/{id}/balance`. See
[02-system-architecture.md](./02-system-architecture.md).

**Checkpoint:** you can read a live, ledger-derived balance per seller.

---

## Step 6 — Schedule payouts

Pay sellers out on a schedule (e.g. weekly). You build a **PayoutBatch** on the
ledger from the seller's `seller_payable` balance; the ledger then calls the
gateway to actually move the money. This is the one flow where the ledger
initiates and the gateway executes — see the payout data flow in
[02-system-architecture.md](./02-system-architecture.md#5-data-flow-a-payout).

```js
// 1. Build the batch from the seller's payable balance (ledger).
const batch = await obol.ledger.createPayoutBatch({
  seller_id:     "sell_atelier",
  scheduled_for: "2026-09-18T18:00:00Z"
});
// => { id: "pyt_0001", seller_id: "sell_atelier",
//      amount: { amount_minor: 11447, currency: "EUR" },
//      status: "scheduled" }
```

Under the hood, the ledger `payouts` module:

1. reads `seller_payable:sell_atelier` (€114.47),
2. creates the batch `pyt_0001` in state `scheduled` and emits
   `payout.scheduled`,
3. calls the gateway `POST /v1/payouts` to move the money,
4. the gateway runs the processor payout and emits `payout.paid`,
5. the ledger consumes `payout.paid`, marks `pyt_0001` `paid`, and **debits
   `seller_payable:sell_atelier`** by €114.47.

Batch lifecycle:

```
   scheduled ──▶ processing ──▶ paid    (seller_payable debited; balance ↓)
       └──────────────────────▶ failed  (no debit; balance unchanged; retry later)
```

Poll or subscribe for completion:

```js
const done = await obol.ledger.getPayoutBatch("pyt_0001");
// => { id: "pyt_0001", status: "paid",
//      processor_ref: "mockproc_payout_Q3xL", ... }
```

After a paid batch, `seller_payable:sell_atelier` returns toward zero — Obol no
longer owes that money because it has reached the seller's bank.

**Preconditions:** the seller must be `kyc_status = verified` and have a
positive balance in their `payout_currency`. Otherwise the gateway rejects with
`422 seller_not_verified` or `422 insufficient_balance`.

**Checkpoint:** `pyt_0001` reaches `paid`; the seller balance drops accordingly.

---

## Step 7 — Handle refunds

If a buyer returns an item, issue a **Refund** against the charge. This reverses
money to the buyer and posts a mirror-image ledger entry that gives fees back
proportionally. The original journal entry is never deleted — the reversal is a
new, opposite entry (immutable audit trail).

**Full-charge refund:**

```js
const refund = await obol.refunds.create("chg_0001", {
  reason: "buyer_returned_item"
  // omit amount to refund the full remaining refundable amount
}, { idempotencyKey: "chg_0001:refund" });
// => { id: "rfnd_0001", charge_id: "chg_0001",
//      amount: { amount_minor: 12000, currency: "EUR" },
//      status: "completed" }
// chg_0001.status -> "refunded"
```

**Partial refund (€40.00):**

```js
const partial = await obol.refunds.create("chg_0001", {
  amount: { amount_minor: 4000, currency: "EUR" },
  reason: "partial_return"
});
// => { id: "rfnd_0002", status: "completed" }
// chg_0001.status -> "partially_refunded"
```

The refund flow spans all three services: in the → Console, an operator clicks
the **Refund** action → `RefundButton` → BFF `refunds` route → gateway
`POST /v1/charges/{id}/refunds` → processor refund → gateway emits
`refund.completed` → ledger `posting` posts the reversal. If you integrate
programmatically you hit the gateway endpoint directly, and the same
`refund.completed` event and ledger reversal follow.

On `refund.completed` (`{ refund_id, charge_id, amount }`) the ledger posts the
reversal: debit `seller_payable:sell_atelier` and `platform_revenue`, credit
`processor_clearing`, with proportional fee give-back. The seller's balance is
reduced accordingly.

**Guardrails:** a refund cannot exceed the charge's remaining refundable amount
(`422 refund_exceeds_charge`), the charge must be settled
(`422 charge_not_settled`), and the currency must match
(`422 currency_mismatch`).

**Checkpoint:** the charge reflects `refunded`/`partially_refunded` and the
seller balance moved down.

---

## Step 8 — Handle disputes

A **Dispute** is a buyer chargeback — the buyer contests the payment with their
card issuer, rather than asking you for a refund. Disputes are distinct from
refunds and are surfaced on the → Console **Disputes** screen.

```
Dispute { id, charge_id, amount (Money), status, created_at }

   open ──▶ won    (resolved for the platform/seller)
     └────▶ lost   (funds returned to the buyer)
```

Recommended handling:

- Treat an `open` dispute as at-risk funds. Consider **not** paying out the
  disputed amount until it resolves — hold it (conceptually against
  `platform_reserve:{platform_id}`) so you are not out-of-pocket if you lose.
- On `won`, no money moves; resume normally.
- On `lost`, the funds go back to the buyer; reconcile the seller's balance
  accordingly.
- Do **not** issue a refund for a charge that already has an open dispute — that
  would double-reverse. Resolve the dispute path instead.

```js
function onDisputeUpdate(dispute) {
  if (dispute.status === "open")  holdFunds(dispute.charge_id, dispute.amount);
  if (dispute.status === "won")   releaseHold(dispute.charge_id);
  if (dispute.status === "lost")  reconcileLoss(dispute.charge_id, dispute.amount);
}
```

**Checkpoint:** disputes are tracked separately from refunds and gate payouts of
at-risk funds.

---

## End-to-end sequence, all together

```
buyer order ─▶ POST /v1/charges (Idempotency-Key)        [Step 3]
                 └─ 201 chg_0001 settled
                    gateway emits payment.authorized, payment.settled
                       └─ ledger posts settlement entry   [Step 4]
                          seller_payable:sell_atelier += 11447

read balance ─▶ GET /v1/accounts/seller_payable:sell_atelier/balance = 11447  [Step 5]

weekly    ─▶ POST /v1/payout-batches -> pyt_0001 scheduled                    [Step 6]
              ledger -> gateway POST /v1/payouts -> processor
                 gateway emits payout.paid
                    ledger marks pyt_0001 paid, debits seller_payable

return     ─▶ POST /v1/charges/chg_0001/refunds -> rfnd_0001 completed        [Step 7]
                 gateway emits refund.completed
                    ledger posts reversal (fees given back proportionally)

chargeback ─▶ Dispute open -> won | lost                                      [Step 8]
```

## Integration checklist

- [ ] API key stored server-side; requests authenticate as `plat_marisqueira`.
- [ ] Sellers created; at least one `kyc_status = verified`.
- [ ] `POST /v1/charges` always sends a stable `Idempotency-Key` per order.
- [ ] Retries reuse the same key; 4xx business errors are not retried blindly.
- [ ] Event handlers are idempotent on `event.id`.
- [ ] Balances are read from the ledger, never maintained as a local counter.
- [ ] Payouts gated on `kyc_status = verified` and positive balance.
- [ ] Refunds respect remaining-refundable and same-currency rules.
- [ ] Disputes tracked separately; at-risk funds held until resolved.

For operational expectations once you are live — latency/availability targets,
retries, incident handling — see
[12-sla-and-operations.md](./12-sla-and-operations.md).
