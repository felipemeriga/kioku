# Obol — Product Overview

> Audience: prospective platform customers, new engineers, and anyone who needs
> the "why" and "what" of Obol before diving into the API or architecture.
> For the internal contract that this document derives from, see the canonical
> domain spec (`SPEC.md`). For the moving parts, see
> [02-system-architecture.md](./02-system-architecture.md); for precise term
> definitions, see [03-domain-glossary.md](./03-domain-glossary.md).

## 1. What Obol is

**Obol is embedded money-movement infrastructure for online marketplaces.**

A marketplace — what Obol calls the **platform** — integrates Obol so it can
accept payments from **buyers**, split each payment between itself and the
**sellers** on its marketplace, hold each seller's money as a balance, and pay
those sellers out to their bank accounts on a schedule. Underneath every one of
those movements, Obol keeps a strict double-entry ledger so that every cent is
accounted for and auditable.

If you have seen "Stripe Connect", Obol occupies the same shape of problem,
deliberately scoped down to a clean core: **charges, refunds, the ledger, and
payouts.** It is not a full acquiring bank, not a card issuer, and not a
general-purpose PSP. It does one thing — move split payments through a
marketplace with correct accounting — and it does that thing precisely.

Obol is *embedded*: the platform's own buyers and sellers never see an "Obol"
brand. The platform integrates Obol's API and dashboard, and to its users the
money movement simply looks like part of the marketplace.

## 2. The problem Obol solves

Marketplaces have a structural money problem that ordinary "accept a payment"
processors do not solve.

Consider a marketplace where independent artisans sell ceramics and textiles.
When a buyer pays €120 for a hand-thrown bowl:

- The money does **not** belong to the marketplace. Most of it belongs to the
  seller who made the bowl.
- The marketplace is entitled to a **cut** — its commission for running the
  storefront, handling discovery, support, and trust.
- The card network and processor take a **fee** for moving the money.
- The seller should be **paid out** later, in a batch, to their own bank —
  not instantly, and not per-order.
- If the buyer returns the bowl, the money must **flow back**, and the
  marketplace's commission and the processor fee have to be unwound
  proportionally.
- Regulators, the marketplace's finance team, and the sellers themselves all
  need to trust that the numbers are **exactly right**, down to the cent, with
  a full audit trail.

Building this yourself means building: a fee/pricing engine, an idempotent
payment edge, a processor integration, a double-entry accounting core that can
never drift, a payout scheduler, a refund/dispute reversal engine, and a
dashboard for the finance operators. That is months of specialized,
correctness-critical work in a domain where a rounding bug is a real financial
liability.

**Obol is that stack, as a service.** The platform integrates a small REST API
and a dashboard, and Obol handles fee computation, the ledger, payouts,
refunds, and disputes.

## 3. The actors

Obol's domain has three human-facing actors and Obol itself. Precise
definitions live in [03-domain-glossary.md](./03-domain-glossary.md); the
short version:

### Platform
The marketplace. **Obol's direct, paying customer.** The platform holds the
relationship with buyers and sellers, sets its own commission rate (the
`default_platform_fee_bps`), integrates the Obol API, and operates the Obol
Console dashboard.

- Entity: `Platform { id, name, country, default_platform_fee_bps, created_at }`
- Sample: `plat_marisqueira` — "Marisqueira Marketplace", country `PT`,
  `default_platform_fee_bps = 290` (a 2.9% commission).

### Seller
A sub-merchant who sells through the platform's marketplace. The seller earns
the bulk of each charge (their **net**), accrues a balance with Obol, and is
paid out on a schedule to a bank account in their payout currency. Before a
seller can be paid out, they must clear **KYC** (Know Your Customer)
verification.

- Entity: `Seller { id, platform_id, display_name, kyc_status, payout_currency,
  created_at }`
- Samples: `sell_atelier` — "Atelier Costa" (KYC `verified`, EUR) and
  `sell_ceramica` — "Cerâmica do Vale" (KYC `verified`, EUR).

### Buyer
The end customer who pays for an order on the marketplace. The buyer is the
source of the money. Obol does not store a rich buyer profile — a buyer appears
in the domain as the payer behind a **Charge**. Buyers are who **Disputes**
come from (a chargeback is a buyer disputing a charge with their card issuer).

### Obol
The infrastructure provider running the three services (gateway, ledger,
console) that make all of the above work. Obol never owns the money
economically — it is a custodian and a bookkeeper — but it moves it and records
it.

## 4. The money-movement story (high level)

Here is the life of one payment, end to end, in plain terms. The concrete
numbers throughout are Obol's fixed sample charge `chg_0001`.

1. **A buyer pays.** A buyer checks out an order on Marisqueira Marketplace for
   **€120.00**. The platform calls Obol to create a **Charge**. Obol authorizes
   and settles the payment through its processor adapter. This is
   `chg_0001`, amount `{ 12000, "EUR" }`.

2. **Obol splits the money.** Obol's pricing engine computes the split from the
   platform's fee rate of `290` bps (2.9%):
   - **Platform fee:** `round_half_even(12000 * 290 / 10000)` = `348` →
     **€3.48** to the platform as revenue.
   - **Processor fee:** `205` → **€2.05**, the cost of moving the money.
   - **Seller net:** `12000 − 348 − 205` = `11447` → **€114.47** owed to the
     seller, `sell_atelier`.

3. **The ledger records it.** When the charge settles, Obol's ledger posts a
   balanced double-entry **JournalEntry**: money in from the processor, the
   platform's fee to revenue, the processor's fee to expense, and the seller's
   net into the seller's payable balance. Debits equal credits, always.

4. **The seller accrues a balance.** `sell_atelier`'s balance with Obol grows
   by €114.47. The seller has not been paid yet — Obol is holding the money and
   owes it to them (a liability on Obol's books: `seller_payable:sell_atelier`).

5. **Obol pays the seller out.** On a schedule (say, weekly), Obol builds a
   **PayoutBatch** from the seller's accrued balance and moves that money to the
   seller's bank via the processor. When it lands, the ledger reduces the
   seller's payable to reflect that Obol no longer owes it.

6. **If something reverses.** If the buyer returns the bowl, the platform issues
   a **Refund** and Obol posts a mirror-image ledger entry — money flows back
   out, and the fees are unwound proportionally. If the buyer files a chargeback
   with their bank instead, that appears as a **Dispute**. The original journal
   entry is never deleted; the reversal is a new, opposite entry, so the audit
   trail is immutable.

The single most important property of this whole story: **the books always
balance.** Every movement is double-entry, and Obol enforces
`sum(debits) == sum(credits)` on every entry it posts.

## 5. The product surface

What a platform actually interacts with breaks into four capabilities. Each maps
onto concrete API endpoints (see
[04-gateway-api-reference.md](./04-gateway-api-reference.md)) and console
screens.

### Charges
Accept a buyer payment and split it. A charge moves through states
`pending → authorized → settled`, or ends `failed`. Later it may become
`refunded` or `partially_refunded`.

- API: `POST /v1/charges` (with an `Idempotency-Key` header),
  `GET /v1/charges/{id}`.
- The platform sends the order amount; Obol computes the fee split and returns
  the full charge including `platform_fee`, `processor_fee`, and status.

### Refunds
Reverse all or part of a charge. Obol moves money back to the buyer through the
processor and posts the reversing ledger entry, giving back fees
proportionally.

- API: `POST /v1/charges/{id}/refunds`.
- A refund has its own lifecycle: `pending → completed`, or `failed`.

### Balances
See what Obol owes each seller (and what is held in reserve). Balances are
**derived from the ledger** — they are not a stored counter that can drift, they
are the sum of the journal lines for an account.

- API: `GET /v1/accounts/{account_id}/balance` and `.../statement` on the
  ledger.
- Console: the **Balances** screen.

### Payouts
Move a seller's accrued balance to their bank on a schedule. Obol builds a
**PayoutBatch** from the seller's `seller_payable` balance and executes it
through the processor. A batch moves `scheduled → processing → paid`, or
`failed`.

- API: `POST /v1/payouts` (gateway executes the move);
  `POST /v1/payout-batches` (ledger builds the batch).
- Console: the **Payouts** screen.

Cutting across all four is a fifth concern — **Disputes** — surfaced on the
console's Disputes screen: a buyer chargeback against a charge, with states
`open → won | lost`.

## 6. Positioning

**Who Obol is for.** Online marketplaces that need to accept split payments and
pay out third-party sellers — artisan marketplaces, service marketplaces,
rental platforms, creator platforms — that want correct money movement and
accounting without building a payments and ledger stack from scratch.

**What Obol is deliberately not.** Obol is not a general merchant processor for
single-party payments, not an issuing/card program, not a full banking-as-a-
service platform, and not a tax or invoicing product. It is scoped to the
marketplace split-payment core: **charges, refunds, ledger, payouts.**

**Why the scope is a feature.** By constraining itself to this core, Obol can
guarantee the property that matters most in payments: **the ledger is always
correct.** Every money movement is double-entry, fees are computed with banker's
rounding on integer minor units (never floats), events are idempotent, and
balances are derived from the immutable journal rather than mutated counters.

**How Obol is built.** Three focused services — `obol-gateway` (the payment API
edge), `obol-ledger` (the double-entry accounting core), and `obol-console` (the
merchant dashboard) — with a clean synchronous edge and an event-driven
accounting core. That architecture, and the reasoning behind it, is the subject
of [02-system-architecture.md](./02-system-architecture.md).

## 7. Where to go next

- **Integrating Obol as a marketplace?** Start with the end-to-end
  [11-integration-guide.md](./11-integration-guide.md).
- **Need the exact API?** See
  [04-gateway-api-reference.md](./04-gateway-api-reference.md).
- **Running Obol in production?** See
  [12-sla-and-operations.md](./12-sla-and-operations.md).
- **Confused by a term?** Everything is defined in
  [03-domain-glossary.md](./03-domain-glossary.md).
