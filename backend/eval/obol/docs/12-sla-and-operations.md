# Obol — SLA and Operations

> Service-level targets and the operational runbook for running Obol in
> production: health checks, event backlog handling, retries, incident
> severities, on-call, monitoring signals, and capacity assumptions. Numbers
> here are the committed targets for the three services described in
> [02-system-architecture.md](./02-system-architecture.md). For terms, see
> [03-domain-glossary.md](./03-domain-glossary.md); for the API surface, see
> [04-gateway-api-reference.md](./04-gateway-api-reference.md).

## 1. Scope and definitions

- **Availability** is measured per calendar month as
  `successful_requests / total_valid_requests`, excluding client `4xx` errors
  (those are the caller's fault, not Obol's).
- **Latency** targets are stated as percentiles (p50 / p95 / p99) of
  server-side processing time, excluding time spent in the external processor
  where noted.
- A **request** is a single HTTP call to a public endpoint. Event processing is
  measured separately as **end-to-end lag** (event emitted → journal posted).
- The month is the SLA window. Error budget is `1 − availability_target`.

---

## 2. Service-level targets

### 2.1 obol-gateway (the payment API edge)

The gateway is the tier users wait on, so it carries the tightest targets.

| Metric | Target |
|---|---|
| Availability (monthly) | **99.95%** (≈ 21.9 min/month error budget) |
| `POST /v1/charges` latency, excl. processor | p50 40 ms · p95 120 ms · p99 250 ms |
| `POST /v1/charges` latency, incl. processor | p50 300 ms · p95 800 ms · p99 1500 ms |
| `GET /v1/charges/{id}` latency | p50 15 ms · p95 60 ms · p99 120 ms |
| `POST /v1/charges/{id}/refunds`, incl. processor | p50 350 ms · p95 900 ms · p99 1800 ms |
| `POST /v1/payouts`, incl. processor | p50 400 ms · p95 1000 ms · p99 2000 ms |

Notes:

- The "excl. processor" charge target isolates gateway overhead (idempotency
  check, `pricing` computation, event publish). The "incl. processor" target is
  what the caller actually experiences.
- Idempotency check + fee computation must add **< 20 ms p99** on their own —
  they run before the processor call and must not dominate.

### 2.2 obol-ledger (the accounting core)

The ledger is measured on both its query API and its event-processing lag.

| Metric | Target |
|---|---|
| Availability (monthly) | **99.9%** (≈ 43.8 min/month error budget) |
| `GET /v1/accounts/{id}/balance` latency | p50 25 ms · p95 90 ms · p99 200 ms |
| `GET /v1/accounts/{id}/statement` latency | p50 40 ms · p95 150 ms · p99 350 ms |
| `POST /v1/payout-batches` latency, excl. gateway | p50 60 ms · p95 200 ms · p99 450 ms |
| **Event end-to-end lag** (emit → posted) | p50 500 ms · p95 2 s · p99 5 s |
| Posting correctness | **100%** — every entry balances |

Notes:

- The ledger is **eventually consistent** by design; balances reflect settled
  charges within the event lag above. A charge returns `settled` from the
  gateway before its journal entry is posted — this is expected (see the
  sync-vs-event boundary in
  [02-system-architecture.md](./02-system-architecture.md)).
- "Posting correctness 100%" is not a percentile — it is an invariant. A single
  unbalanced entry is a **Sev-1**. The ledger rejects unbalanced entries at
  write time, so this failure means a bug got past that guard.

### 2.3 obol-console (the dashboard)

The console reads projections; its targets are looser and dominated by the
services behind it.

| Metric | Target |
|---|---|
| Availability (monthly) | **99.5%** |
| SPA initial load (TTI) | p95 < 3 s |
| BFF proxied read (balances/statements/payouts) latency | p95 < ledger p95 + 50 ms |
| Refund action end-to-end (BFF → gateway) | p95 < gateway refund p95 + 50 ms |

The console has no independent correctness SLA — it must never *invent* numbers;
it displays what the gateway and ledger return.

---

## 3. Health checks

Every service exposes a liveness and a readiness probe.

| Service | Liveness | Readiness | Ready means |
|---|---|---|---|
| obol-gateway | `GET /healthz` | `GET /readyz` | idempotency store reachable, processor adapter reachable, event bus writable |
| obol-ledger | `GET /healthz` | `GET /readyz` | Postgres reachable, event consumer lag < warn threshold |
| obol-console | `GET /healthz` | `GET /readyz` | BFF can reach gateway and ledger |

Rules:

- **Liveness** answers "is the process wedged?" A failing liveness probe
  restarts the instance. It must not depend on downstream services (a processor
  outage should not restart every gateway pod).
- **Readiness** answers "should this instance receive traffic?" A failing
  readiness probe removes the instance from the load balancer without killing
  it.
- Readiness for the ledger includes **consumer lag**: if event lag exceeds the
  warn threshold (see §4), the instance keeps consuming but is de-prioritized
  for reads that need freshness.

---

## 4. Event backlog and consumer lag

The gateway→ledger boundary is event-driven with at-least-once delivery.
Backlog is the primary health signal for the accounting core.

**Definitions:**

- **Backlog depth** — number of undelivered events on the bus.
- **Consumer lag** — age of the oldest unprocessed event (wall-clock).

**Thresholds:**

| Level | Consumer lag | Backlog depth | Action |
|---|---|---|---|
| Normal | < 2 s | < 1,000 | none |
| Warn (page- if-sustained) | 2 s – 30 s | 1k – 20k | investigate; scale ledger consumers |
| Critical (page now) | > 30 s | > 20k | Sev-2; balances materially stale |
| Sev-1 | > 5 min | growing unbounded | accounting is falling behind; incident |

**Why this matters:** balances are derived from posted journal lines, so a
growing lag means the Balances screen and payout-batch building are working from
stale data. Payout batches must **not** be built while lag is Critical — a batch
built from a stale `seller_payable` could over- or under-pay.

**Recovery:** scale ledger consumer replicas horizontally; the posting module is
idempotent on `event.id`, so more consumers is always safe. Never "skip"
events to drain a backlog — every event is a money fact.

---

## 5. Retries and idempotency

Retries are safe *because* Obol is idempotent at two layers. Operators and
integrators must respect these.

- **Gateway `POST /v1/charges`** — idempotent on the `Idempotency-Key` header,
  checked before any processor call. A retried charge with the same key returns
  the original result. Keys honored ≥ 24h. See
  [04-gateway-api-reference.md](./04-gateway-api-reference.md#idempotency--the-idempotency-key-header).
- **Event consumers** — idempotent on `event.id`. At-least-once delivery is
  handled by dedup on the event id; duplicates are dropped, not double-posted.
- **Gateway → processor** — the processor adapter uses the same idempotency key
  downstream so a gateway retry does not double-hit the card network.
- **Ledger → gateway payout call** (`POST /v1/payouts`) — carries an idempotency
  key derived from the `batch_id` so a retried payout does not pay a seller
  twice.

**Retry policy (internal calls):** exponential backoff, base 200 ms, factor 2,
max 5 attempts, jittered, cap 10 s. `5xx` and timeouts are retried; `4xx`
business errors are not. Failed payouts leave the batch `failed` with **no**
`seller_payable` debit, so they are safe to retry on the next schedule.

---

## 6. Incident severities

| Severity | Definition | Examples | Response |
|---|---|---|---|
| **Sev-1** | Money is wrong or at risk; or full outage of a core money path | unbalanced journal entry; double-charge; double-payout; gateway charges fully down; ledger event lag > 5 min and growing | page on-call immediately; incident commander; all-hands until mitigated |
| **Sev-2** | Degraded core path; correctness intact but users impacted | charge p99 breaching for > 15 min; event lag Critical (> 30 s); balances stale; console down | page on-call; mitigate within the hour |
| **Sev-3** | Localized/partial degradation, workaround exists | elevated `422`s from one seller; single console screen slow; one processor route flaky | ticket + next-business-day; monitor |
| **Sev-4** | Cosmetic or low-impact | dashboard styling, non-critical log noise | backlog |

**Golden rule:** anything that could make the ledger not balance, or move money
twice or not at all, is **Sev-1** regardless of blast radius. Correctness
outranks availability.

**Mitigation-first:** stop the bleeding before root-causing. For a suspected
double-movement, the first action is to **halt payouts** (feature flag on the
ledger `payouts` module) and freeze the affected batch, then investigate.

---

## 7. On-call

- **Rotation:** one primary + one secondary, weekly, following the sun where
  staffing allows. Separate expertise tags for gateway (Go), ledger
  (Python/accounting), and console.
- **Acknowledgement SLA:** Sev-1 page acked within **5 min**; Sev-2 within
  **15 min**.
- **Escalation:** primary → secondary after 10 min unacked → engineering lead →
  incident commander for Sev-1.
- **Runbook access:** on-call must be able to reach: bus/backlog dashboard,
  ledger consumer scaling, the payout-halt flag, processor status page, and the
  balance-reconciliation job.
- **Handoff:** every rotation ends with a written handoff of open incidents,
  degraded conditions, and any suppressed alerts.

---

## 8. Monitoring signals

Instrument and alert on the following. Grouped by the question they answer.

**Is the edge healthy? (gateway)**

- Request rate, error rate (`5xx`), latency p50/p95/p99 per endpoint.
- Idempotency store hit/miss and latency (must stay < 20 ms p99).
- Processor call latency and decline rate.
- Event publish success rate (a publish failure means the ledger will never see
  the fact — treat elevated publish failures as Sev-2).

**Is accounting keeping up? (ledger)**

- Event consumer lag and backlog depth (§4) — the top-line accounting signal.
- Posting success rate; **unbalanced-entry count (must be 0)**.
- Duplicate-event drop rate (confirms idempotency is engaging, not silently
  failing).
- Balance query latency; payout-batch build latency and outcome
  (`paid`/`failed`).
- Postgres health: connection pool saturation, replication lag, disk.

**Is the dashboard usable? (console)**

- BFF error rate and upstream (gateway/ledger) error attribution.
- SPA load time; refund-action success rate.

**Cross-cutting reconciliation:**

- A periodic **reconciliation job** re-derives the sum of all account balances
  and asserts the global books balance to zero across debits/credits. A nonzero
  result is a **Sev-1**. Run at least hourly.
- Per-seller check: `sum(seller_payable settlements) − sum(payouts) − sum(refund
  reversals)` must equal the derived `seller_payable:{seller}` balance.

**Alert hygiene:** page only on symptoms that need human action now (Sev-1/2).
Everything else is a dashboard or a ticket. Every page must link to the relevant
runbook section.

---

## 9. Capacity assumptions

Sizing baseline for a platform of Marisqueira Marketplace's scale, with headroom
to 5×.

| Dimension | Baseline | Headroom target |
|---|---|---|
| Charge throughput | 50 charges/sec sustained, 200/sec peak | 1,000/sec |
| Events emitted | ~2 per charge (`authorized`, `settled`) → 100/sec sustained | 2,000/sec |
| Refund rate | ≤ 5% of charges | 15% |
| Payout batches | daily/weekly per seller; thousands of sellers per platform | 10k batches/run |
| Ledger write rate | 1 balanced `JournalEntry` (≈ 4 lines) per settled charge | scales with charges |
| Balance reads (console + integrators) | 10× charge rate (read-heavy) | 10,000/sec |

Scaling model:

- **Gateway** scales horizontally on request rate; stateless replicas behind the
  load balancer. Autoscale target: keep CPU < 60% and charge p95 within SLA.
- **Ledger** scales consumers horizontally on backlog/lag; scales query replicas
  on read latency. Postgres is the ceiling — watch connection pool and write
  IOPS; the immutable journal grows monotonically, so plan storage and
  archival/partitioning by `created_at`.
- **Console** scales the BFF on request rate; it holds no state.

**Data growth:** the journal is append-only and never deleted (immutable audit
trail — refunds post opposite entries, not deletes). Budget storage growth
linear in charges + refunds + payouts, and partition/archive cold journal data
by month while keeping it queryable for statements and reconciliation.

---

## 10. Operational runbook — quick reference

| Symptom | First check | Likely action |
|---|---|---|
| Charge p99 breaching | processor latency vs gateway overhead | if processor-bound, check processor status; if gateway-bound, scale gateway |
| Balances look stale | ledger consumer lag (§4) | scale ledger consumers; do **not** build payout batches while Critical |
| Event backlog growing | consumer replica count, Postgres write IOPS | scale consumers; check DB; never skip events |
| Unbalanced entry alerted | reconciliation job output | **Sev-1**: halt payouts, freeze affected data, root-cause the posting bug |
| Double-payout suspected | payout idempotency key on `batch_id` | **Sev-1**: halt payouts flag, freeze batch, reconcile seller_payable |
| Payout batch `failed` | processor decline reason, seller `kyc_status` | if `seller_not_verified`, fix KYC; otherwise safe to retry next schedule (no debit posted) |
| Idempotency `409`s spiking | integrator reusing keys with changed bodies | coordinate with integrator; confirm per-operation keys |
| Console shows nothing | BFF → gateway/ledger reachability (`/readyz`) | check upstream health; console has no data of its own |

For the integration-side expectations that pair with these operations, see
[11-integration-guide.md](./11-integration-guide.md).
