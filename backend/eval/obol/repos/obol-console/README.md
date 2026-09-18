# obol-console

The **marketplace operator's dashboard** for [Obol](../../SPEC.md) — embedded
money-movement infrastructure for online marketplaces. It is a **React 18 + Vite
single-page app** backed by a **Node/Express BFF**.

The console lets the platform operator (here, *Marisqueira Marketplace* —
`plat_marisqueira`) watch transactions, read seller balances, schedule payouts,
review disputes, and — the money-moving action — **issue refunds**.

> The console **never touches the card processor**. It reads from and writes to
> two upstream Obol services **through its own BFF**:
>
> - **obol-gateway** (Go) — owns charges, refunds, payouts, idempotency, the
>   processor adapter. The console proxies **refunds** and **charge reads** here.
> - **obol-ledger** (Python/FastAPI) — the double-entry accounting core. The
>   console proxies **balances, statements, and payout batches** here.

---

## Architecture

```
┌──────────────────────────── browser ────────────────────────────┐
│  React SPA (web/)                                                 │
│    pages: Transactions · Balances · Payouts · Disputes           │
│    hooks: useTransactions · useBalances · useRefund · usePayouts  │
│    api/client.ts  ── only ever calls  /api/*  (same origin)       │
└───────────────────────────────┬──────────────────────────────────┘
                                 │  HTTP /api/*
┌───────────────────────────────▼──────────────────────────────────┐
│  Express BFF (bff/)                                                │
│    routes: refunds · charges · balances · statements · payouts    │
│            · disputes · sellers · healthz                         │
│    clients: gatewayClient · ledgerClient  (typed fetch wrappers)  │
│    middleware: requestId · errorHandler                           │
└───────────┬───────────────────────────────────┬──────────────────┘
            │ refunds, charges                   │ balances, statements,
            │ POST /v1/charges/{id}/refunds      │ payout-batches
            ▼                                    ▼
     ┌──────────────┐                     ┌──────────────┐
     │ obol-gateway │  ──emits events──▶  │ obol-ledger  │
     │    (Go)      │  payment.settled,   │ (FastAPI)    │
     │              │  refund.completed…  │              │
     └──────────────┘                     └──────────────┘
```

`shared/contracts/` holds the TypeScript types that mirror the SPEC (Money,
Charge, Refund, PayoutBatch, Account, event envelope). **Both** the web app and
the BFF import them, so the wire contract is defined exactly once.

### Money

Money is always `{ amountMinor: number; currency: string }` (integer minor units
+ ISO-4217), never a float — see `shared/contracts/money.ts`. `formatMoney`
turns `{ 12000, "EUR" }` into `€120.00`. Upstream services speak the SPEC's
snake_case `{ amount_minor, currency }`; the BFF clients
(`bff/src/clients/mapping.ts`) are the single place that translates.

---

## Screens

| Screen             | Route           | What it shows | Talks to (via BFF) |
| ------------------ | --------------- | ------------- | ------------------ |
| **Transactions**   | `/transactions` | All charges, filterable by seller/status, each row with a **Refund** action | gateway |
| **Balances**       | `/balances`     | A seller's **payable balance** (available/pending) + statement lines | **ledger** |
| **Payouts**        | `/payouts`      | Payout batches + "Schedule payout" | ledger (→ gateway) |
| **Disputes**       | `/disputes`     | Buyer chargebacks against charges | ledger projection |

---

## The two ground-truth call chains

These two flows are the point of the console and are traceable end-to-end in the
code.

### 1. Refund action (write → gateway)

```
web/src/components/RefundButton.tsx
  → web/src/hooks/useRefund.ts
    → web/src/api/client.ts  consoleApi.createRefund()
      → POST /api/charges/:chargeId/refunds
        → bff/src/routes/refunds.ts            (mints Idempotency-Key)
          → bff/src/clients/gatewayClient.ts   createRefund()
            → gateway  POST /v1/charges/{id}/refunds
              → processor.refund → emit refund.completed
                → ledger posts the reversal journal entry
```

### 2. Balance display (read → ledger)

```
web/src/pages/BalancePage.tsx
  → web/src/hooks/useBalances.ts
    → web/src/api/client.ts  consoleApi.getSellerBalance()
      → GET /api/sellers/:sellerId/balance
        → bff/src/routes/balances.ts           (resolves seller_payable:{id})
          → bff/src/clients/ledgerClient.ts    getBalance()
            → ledger  GET /v1/accounts/{account_id}/balance
```

---

## Fixed sample data

Matches SPEC §"Fixed sample data" so examples line up across every repo and doc:

- Platform: `plat_marisqueira` — "Marisqueira Marketplace", `PT`, `290` bps (2.9%).
- Sellers: `sell_atelier` ("Atelier Costa", EUR), `sell_ceramica` ("Cerâmica do Vale", EUR).
- Example charge: `chg_0001` — seller `sell_atelier`, amount **€120.00**
  (`{ 12000, "EUR" }`), platform_fee **€3.48** (`{ 348, "EUR" }`), processor_fee
  **€2.05** (`{ 205, "EUR" }`), seller net **€114.47** (`{ 11447, "EUR" }`).

The BFF ships a built-in **mock mode**: when `GATEWAY_BASE_URL` /
`LEDGER_BASE_URL` are empty or contain `mock`, it serves the fixtures in
`bff/src/clients/fixtures.ts` so the console runs stand-alone for demos and the
eval harness. Point those env vars at real services to hit them instead.

---

## Running

```bash
npm install            # installs the root + shared + bff + web workspaces
cp .env.example .env   # then set GATEWAY_BASE_URL / LEDGER_BASE_URL (or leave as mock)

npm run dev            # BFF on :8787, Vite SPA on :5173 (proxies /api → BFF)
```

Other scripts:

```bash
npm run build          # builds shared, then bff, then web
npm test               # BFF (supertest + vitest) and web (vitest + testing-library)
npm run typecheck      # strict tsc across bff + web
```

Production single-container image (SPA served by the BFF):

```bash
docker build -t obol-console .
docker run -p 8787:8787 -e GATEWAY_BASE_URL=... -e LEDGER_BASE_URL=... obol-console
```

---

## Layout

```
shared/contracts/   Money, entities, events, api DTOs — shared by web + bff
bff/src/
  server.ts app.ts config.ts deps.ts logger.ts errors.ts
  clients/          httpClient · gatewayClient · ledgerClient · mapping · fixtures
  routes/           refunds · charges · balances · statements · payouts · disputes · sellers · health
  middleware/       requestId · errorHandler · asyncHandler
  __tests__/        refunds.route · balances.route
web/src/
  main.tsx App.tsx
  pages/            Transactions · Balance · Payouts · Disputes
  components/       RefundButton · MoneyAmount · StatusBadge · TransactionTable · PayoutTable · SellerPicker · Layout · QueryState
  hooks/            useTransactions · useBalances · useRefund · usePayouts · useDisputes · useSellers
  api/              http · client
  fixtures/         sampleData
  __tests__/        MoneyAmount · RefundButton · money
```
