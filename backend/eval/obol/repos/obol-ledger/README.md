# obol-ledger

The **double-entry accounting core** for [Obol](../../SPEC.md) — embedded
money-movement infrastructure for online marketplaces.

This service consumes payment events emitted by `obol-gateway` and posts
**immutable, balanced journal entries**. It derives account balances and
statements from those entries, and builds seller **payout batches** — delegating
the actual money movement back to the gateway's `POST /v1/payouts`.

The one hard invariant enforced everywhere: **every journal entry balances**,
`sum(debits) == sum(credits)`, in a single currency.

- **Language:** Python 3.11
- **Framework:** FastAPI + Pydantic v2
- **HTTP client:** httpx (for gateway payout calls)

## Where the ground-truth logic lives

| Concern | Module |
| --- | --- |
| Settlement + refund posting | [`obol_ledger/posting/`](obol_ledger/posting/) (`settlement.py`, `refund.py`) |
| Balance derivation | [`obol_ledger/balances/`](obol_ledger/balances/) (`derive.py`) |
| Payout batch building | [`obol_ledger/payouts/`](obol_ledger/payouts/) (`builder.py`, `gateway_client.py`) |
| Event routing (idempotent) | [`obol_ledger/events/`](obol_ledger/events/) (`dispatcher.py`) |
| Chart of accounts | [`obol_ledger/accounts/`](obol_ledger/accounts/) (`chart.py`) |
| Money value object | [`obol_ledger/money.py`](obol_ledger/money.py) |

## Chart of accounts (from SPEC)

- `processor_clearing` (asset) — money in transit from the card processor
- `platform_revenue` (revenue) — accumulated platform fees
- `processor_fees` (expense) — fees paid to the processor
- `seller_payable:{seller_id}` (liability) — what Obol owes each seller
- `platform_reserve:{platform_id}` (liability) — held funds / risk reserve

## The money model

Money is **always** integer minor units + an ISO-4217 currency — never floats.
Arithmetic is only allowed between same-currency values; fees use banker's
rounding (`round_half_even`). See [`obol_ledger/money.py`](obol_ledger/money.py).

```python
Money(amount_minor=12000, currency="EUR")  # €120.00
```

## Settlement example — charge `chg_0001`

Using the SPEC's fixed sample data (seller `sell_atelier`), on `payment.settled`
for amount `€120.00`, platform fee `€3.48`, processor fee `€2.05`, seller net is
`N = A − P − F = 12000 − 348 − 205 = 11447` (`€114.47`). The posting module
builds:

| Account | Debit | Credit |
| --- | ---: | ---: |
| `processor_clearing` | `12000` | |
| `platform_revenue` | | `348` |
| `processor_fees` | | `205` |
| `seller_payable:sell_atelier` | | `11447` |
| **Total** | **`12000`** | **`12000`** |

Debits equal credits — the entry balances. These exact numbers are reproduced in
[`tests/test_settlement_posting.py`](tests/test_settlement_posting.py).

## Refund reversal

On `refund.completed` for amount `R`, the ledger posts a **new, opposite** entry
(the original is never deleted). The platform fee is refunded proportionally:

```
fee_giveback    = round_half_even(platform_fee * R / original_amount)
seller_clawback = R - fee_giveback

DEBIT  platform_revenue          fee_giveback
DEBIT  seller_payable:{seller}    seller_clawback
CREDIT processor_clearing         R
```

## Payout batches

`POST /v1/payout-batches` derives a seller's `seller_payable` balance, builds a
`PayoutBatch`, and calls gateway `POST /v1/payouts` to move the money (status →
`processing`). When the gateway later emits `payout.paid`, the ledger posts the
balancing debit against `seller_payable` (status → `paid`).

## Events consumed

| Event type | Effect |
| --- | --- |
| `payment.settled` | posts the settlement entry |
| `refund.completed` | posts the reversal entry |
| `payout.paid` | marks the batch paid + debits `seller_payable` |

All other event types are acknowledged and ignored. Consumption is **idempotent
on `event.id`** — a redelivered event posts nothing new.

## HTTP API

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/internal/events` | consume an event envelope `{ id, type, ts, data }` |
| `GET` | `/v1/accounts/{account_id}/balance` | derived balance for an account |
| `GET` | `/v1/accounts/{account_id}/statement` | ordered statement + closing balance |
| `POST` | `/v1/payout-batches` | build + submit a payout batch |
| `GET` | `/v1/payout-batches/{batch_id}` | fetch a payout batch |
| `GET` | `/healthz`, `/readyz` | liveness / readiness |

Account ids in the path are the canonical chart names, e.g.
`seller_payable:sell_atelier`.

## Running

```bash
make install          # uv pip install -e ".[dev]"  (falls back to pip)
make run              # uvicorn on :8081
make test             # pytest
```

Configuration is via environment (see [`.env.example`](.env.example)); notably
`OBOL_GATEWAY_URL` points the payout builder at the gateway.

### Docker

```bash
make docker
docker run -p 8081:8081 -e OBOL_GATEWAY_URL=http://gateway:8080 obol-ledger:latest
```

## Cross-repo relationships (SPEC)

- **Fee: computed vs recorded** — gateway `pricing` computes `platform_fee`;
  ledger `posting` records it to `platform_revenue`.
- **Refund flow** — console `RefundButton` → BFF → gateway refund handler →
  `refund.completed` → ledger `posting` posts the reversal.
- **Payout batching** — ledger `payouts` builds the batch from `seller_payable`,
  calls gateway `POST /v1/payouts`; gateway emits `payout.paid`; ledger marks the
  batch paid.
- **Balance read** — console `BalancePage` → BFF → ledger `balances`.

## Project layout

```
obol_ledger/
  money.py            Money value object (minor units, banker's rounding)
  errors.py           typed errors + FastAPI exception handlers
  config.py           env-sourced settings
  ids.py              prefixed snake id generation
  state.py            app state container + FastAPI deps
  main.py             FastAPI app factory
  sample_data.py      SPEC fixed sample data (chg_0001)
  models/             pydantic models (account, journal_entry, journal_line,
                      payout_batch, event envelope)
  posting/            settlement + refund posting  (ground truth)
  balances/           balance + statement derivation  (ground truth)
  payouts/            payout batch builder + gateway client  (ground truth)
  accounts/           chart of accounts + registry
  events/             envelope parsing + idempotent dispatcher
  repository/         in-memory stores (journal, batches, processed events)
  api/                routers (events, accounts, payout_batches, health)
tests/                money, settlement, refund, balances, idempotency, payouts, api
```
