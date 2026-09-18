# Security and Compliance

> Audience: every engineer touching Obol, plus security, compliance, and
> operations. Obol moves other people's money and handles cardholder and
> seller-identity data, so security is a product requirement, not an add-on. This
> document sets out PCI scope and how Obol minimizes it, PII handling for sellers
> (KYC), encryption, the audit log, the access-control model, key rotation, data
> retention, and incident response for a suspected breach. These are concrete
> policies, not aspirations.
>
> Companion reading: the immutable audit-source ledger is in
> [05 — Ledger Model and Invariants](05-ledger-model-and-invariants.md); the
> events whose integrity we protect are in
> [07 — Event Catalog](07-event-catalog.md); in-region data residency is recorded
> as [ADR-008](10-architecture-decision-records.md#adr-008-in-region-data-residency-eu-sellers).

## 1. Threat model in one paragraph

Obol's crown jewels are, in order: (1) the ability to move money (a compromised
payout path could drain seller balances); (2) cardholder data (raw PANs, if we
held them, would make us a prime target); (3) seller PII / KYC data (identity
documents, bank details). The design goal is to hold as little sensitive data as
possible, isolate the money-movement path, make every privileged action
auditable, and detect and contain compromise quickly. Everything below serves
that goal.

## 2. PCI DSS scope and how Obol minimizes it

### 2.1 The scoping principle

PCI DSS scope is driven by where cardholder data (the PAN — primary account
number — and related data) is stored, processed, or transmitted. The single most
effective way to reduce PCI burden, audit cost, and breach blast radius is to
**never touch raw card data at all**. Obol is architected so that no Obol system
stores, processes, or transmits a raw PAN.

### 2.2 Tokenization — no raw PAN storage

- Card details are captured **client-side** by the platform's checkout using the
  processor's tokenization SDK/hosted fields. The raw PAN goes directly from the
  buyer's browser to the **card processor**, never through Obol's servers.
- The processor returns an opaque **payment-method token**. Obol's `Charge` is
  created against that token via `POST /v1/charges`, and the gateway `processor`
  adapter references the token, not a PAN.
- The `processor_ref` stored on a `Charge` / `PayoutBatch` is an opaque processor
  reference, not card data.
- **No Obol database column, log line, event payload, or backup ever contains a
  PAN, CVV, magnetic-stripe data, or a full expiry+PAN combination.** This is
  enforced by policy *and* by automated log/payload scanning (§7.5).

Because the raw PAN never enters Obol's environment, Obol's PCI scope collapses to
the minimal tier appropriate for a merchant/processor integration that outsources
cardholder data to a tokenizing processor (SAQ A-style scope), rather than the
full scope of an entity that stores PANs. Concretely, that removes the systems
that would otherwise store or process card data from the audit boundary.

### 2.3 What is in scope

Even with tokenization, the following remain security-sensitive and inside our
controls (though outside strict PAN-storage PCI scope): payment-method **tokens**
(treated as secrets — a stolen token could initiate a charge), the money-movement
path (`POST /v1/charges`, `POST /v1/payouts`), the event bus, and the ledger.
These are protected by the access controls, encryption, and auditing in the rest
of this document.

## 3. Seller PII and KYC handling

Sellers (`sell_atelier`, `sell_ceramica`, …) undergo KYC before their `kyc_status`
becomes `verified` (spec: `pending | verified | rejected`). KYC produces PII we
must protect: legal name, identity-document data, and bank/payout details.

Policies:

- **Data minimization.** Obol stores only the KYC fields required to satisfy
  regulatory obligations and to pay out. Raw identity-document images, where
  captured, are handled by the KYC provider and referenced by token/id in Obol
  wherever possible, mirroring the card-tokenization approach.
- **Bank/payout details are secrets.** They are encrypted at rest with envelope
  encryption (§4) and are never emitted in events, logs, or the console UI beyond
  a masked last-few-digits display.
- **Field-level access control.** KYC PII is readable only by roles with an
  explicit need (compliance, and the payout path for bank details). The console's
  ordinary Transactions/Balances/Payouts screens do **not** expose raw KYC PII.
- **`kyc_status` is the only KYC signal most systems need.** The gateway and
  ledger gate behavior on `kyc_status` (e.g. a seller must be `verified` to be
  paid out) without reading the underlying documents. This keeps PII access
  narrow.
- **PII in events: none.** The event catalogue (`payment.*`, `refund.*`,
  `payout.*` in [07 — Event Catalog](07-event-catalog.md)) carries ids and
  `Money` amounts only — no names, no bank details, no documents. This is a
  deliberate design property: the event bus, being a widely-consumed pipe, must
  never become a PII distribution channel.

## 4. Encryption

### 4.1 In transit

- **All external and internal service-to-service traffic uses TLS 1.2+**, with
  1.3 preferred. This covers buyer → processor tokenization, platform → gateway
  (`POST /v1/charges`), console BFF → gateway/ledger, and ledger → gateway
  (`POST /v1/payouts`).
- Internal calls additionally use **mutual TLS (mTLS)** where the caller identity
  matters — notably ledger→gateway payout execution and gateway→ledger event
  delivery (`POST /internal/events`) — so a service can cryptographically prove
  who it is, not just that the channel is encrypted.
- No sensitive data ever traverses an unencrypted channel. Plaintext HTTP is
  refused, not redirected.

### 4.2 At rest

- **Databases and backups are encrypted at rest** (transparent disk/volume
  encryption as a baseline).
- **Secrets and PII use application-level envelope encryption on top of that.**
  Sensitive fields (bank details, KYC data, payment-method tokens) are encrypted
  with a per-record data key, which is itself encrypted by a master key held in a
  managed KMS. The plaintext master key never leaves the KMS. This means a stolen
  database dump is not sufficient to read PII — the attacker also needs KMS
  access, which is separately controlled and audited.
- **The ledger's journal is encrypted at rest** like any other store, but note
  its integrity property is separate: immutability
  ([05 — Ledger Model and Invariants §6](05-ledger-model-and-invariants.md#6-immutability-refunds-post-reversals-never-mutations))
  makes it tamper-evident, which the audit log leans on (§5).

## 5. The audit log {#audit-log}

Every privileged or money-affecting action produces an audit record. The audit
log answers "who did what, to what, when, and from where" and is the backbone of
both compliance and incident response.

### 5.1 What is logged

- Every **refund** initiated (console `RefundButton` → BFF → gateway) — actor,
  `charge_id`, `refund_id`, amount, timestamp.
- Every **payout execution** and every payout **state transition**
  (`scheduled → processing → paid/failed`).
- Every **reconciliation discrepancy** and its correcting entry id (see
  [08 — Payouts and Reconciliation §6.3](08-payouts-and-reconciliation.md#63-discrepancy-handling)).
- Every **access to KYC PII / bank details** — read and write.
- Every **key-management operation** (rotation, access grant).
- Every **auth event** — login, role change, failed authorization.

### 5.2 Properties

- **Append-only and tamper-evident.** Audit records are never edited or deleted.
  They are written to an append-only store and periodically anchored (hash-chained
  or checkpoint-hashed) so tampering is detectable. This mirrors the ledger's
  immutable-journal philosophy: the record of what happened is not something the
  system can quietly rewrite.
- **The ledger *is* the financial audit trail.** Because journal entries are
  immutable and carry the triggering `event_id`, the ledger already records the
  complete, ordered history of every cent. The audit log complements it with the
  *human/operator* actions around those movements (who clicked refund, who ran a
  reconciliation correction).
- **Independently stored.** Audit logs are written to a store separate from the
  operational databases, so compromising a service database does not let an
  attacker erase their tracks.
- **Retained** per §8.

## 6. Access-control model

### 6.1 Principle of least privilege

Every human and every service gets the minimum access needed for its job, and
nothing more. Access is role-based and enforced at each service boundary — the BFF
does not "trust the frontend," the gateway does not "trust the BFF," and the
ledger does not "trust the gateway" beyond its authenticated identity.

### 6.2 Human roles (console)

| Role | Can | Cannot |
| ---- | --- | ------ |
| **Support** | View Transactions/Balances/Payouts/Disputes | Initiate refunds or payouts; read raw KYC PII |
| **Operator** | Everything Support can, plus initiate refunds and manage payouts | Read raw KYC documents; manage keys |
| **Compliance** | Read KYC PII / bank details; review disputes | Move money |
| **Admin** | Manage roles and configuration | Bypass the audit log (all admin actions are logged) |

All console access flows through the BFF, which authenticates the operator and
authorizes each action against their role before proxying to gateway or ledger.
The console never calls the processor directly (spec) — it has no processor
credentials at all, which removes an entire class of "compromised dashboard →
drained funds" attack.

### 6.3 Service identities

- **`obol-gateway`** holds processor credentials and is the *only* system that
  can call the processor (charges, refunds, payouts). It is the most sensitive
  service and is isolated accordingly.
- **`obol-ledger`** can call gateway `POST /v1/payouts` (to execute batches) and
  receives events at `POST /internal/events`. It holds **no** processor
  credentials.
- **`obol-console` BFF** can call gateway (refunds) and ledger (balances,
  statements, payouts) but holds **no** processor credentials.
- Service-to-service auth uses mTLS + short-lived credentials (§4.1, §7). A
  service can prove its identity, and every privileged inter-service call is
  authorized against that identity, not merely accepted because it arrived on the
  internal network.

### 6.4 Separation of duties

The money-movement path is deliberately split so no single component or role can
both *decide* to move money and *execute* it unchecked: the console/operator
*initiates* a refund or payout, the gateway *executes* it against the processor,
and the ledger independently *records* and *reconciles* it. A compromise of any
one leg is detectable by the others (e.g. a rogue payout shows up as a
reconciliation discrepancy in
[08 — Payouts and Reconciliation §6](08-payouts-and-reconciliation.md#6-daily-reconciliation)).

## 7. Key rotation and secrets management

- **Central secrets store / KMS.** All secrets — processor credentials, KMS master
  keys, service credentials, signing keys — live in a managed secrets store, never
  in source, config files, container images, or environment variables baked into
  images.
- **Rotation schedule.** Application secrets and service credentials rotate on a
  fixed schedule (at minimum annually; sensitive ones more often) and immediately
  on any suspected compromise. KMS master keys rotate on schedule with envelope
  re-encryption handled by the KMS so data keys are re-wrapped without
  re-encrypting every record.
- **Short-lived credentials.** Service-to-service credentials are short-lived and
  auto-renewed, so a leaked credential expires quickly and rotation is a
  non-event operationally.
- **No shared human access to production secrets.** Humans do not read raw
  production secrets; access is brokered and logged (§5).
- **Rotation is auditable.** Every rotation and every secret-access grant is
  written to the audit log.

### 7.5 Automated leakage scanning

CI and runtime pipelines scan logs, event payloads, and outgoing responses for
patterns that look like PANs, CVVs, or bank details. A match fails the build (in
CI) or triggers an alert and redaction (at runtime). This is the enforcement
mechanism behind the "no PAN ever in logs/events" policy in §2.2 and §3.

## 8. Data retention

- **Ledger journal:** retained for the full regulatory financial-records period
  (multi-year, per applicable EU/PT financial regulation). Immutable, never
  purged early — it is the financial system of record.
- **Audit log:** retained per compliance requirements (multi-year), tamper-evident
  (§5).
- **KYC PII:** retained only as long as required by KYC/AML obligations plus the
  regulatory tail, then deleted or irreversibly anonymized. Retention is tracked
  per record so deletion happens on time, not "eventually."
- **Payment-method tokens:** retained only while an active relationship needs them;
  revoked at the processor and deleted when no longer needed.
- **Operational/PII deletion requests** (data-subject requests) are honored for
  data Obol is not legally required to retain; where financial records must be
  kept, the response explains the legal-retention basis rather than silently
  ignoring the request. Deletions are logged.

## 9. Data residency

EU sellers' data is stored and processed **in-region (EU)**. This is a hard
requirement, recorded and justified in
[ADR-008](10-architecture-decision-records.md#adr-008-in-region-data-residency-eu-sellers).
The fixed sample platform `plat_marisqueira` is in Portugal (`PT`) with EUR
sellers, so all its data — charges, KYC, ledger entries — resides in the EU
region. Cross-region replication of EU personal data outside the EU is not
performed for these tenants.

## 10. Incident response — suspected breach

A concrete runbook for a suspected data or money-movement breach. Speed and
containment beat perfect diagnosis; contain first, investigate second.

### 10.1 Detect and declare

Triggers: leakage-scan alert (§7.5), an unexplained reconciliation discrepancy
([08 — Payouts and Reconciliation](08-payouts-and-reconciliation.md)), anomalous
payout activity, an auth anomaly in the audit log, or an external report. Any
engineer can and must **declare an incident** — err toward declaring.

### 10.2 Contain

1. **Freeze the money-movement path if payouts/refunds are implicated.** Halt
   payout execution (stop the ledger→gateway payout driver) so no further funds
   can leave while investigating. Charges can be paused at the gateway if needed.
2. **Rotate implicated secrets immediately** — processor credentials, service
   credentials, signing keys (§7). Assume anything the attacker may have touched
   is burned.
3. **Revoke compromised sessions / access.** Force re-auth; disable suspected
   accounts.
4. **Isolate** the affected service(s) from the network if active compromise is
   suspected.

### 10.3 Assess

- Use the **audit log** (§5) and the **immutable ledger** to reconstruct exactly
  what happened — because neither can be quietly rewritten, they are trustworthy
  even if a service was compromised. Determine what data was accessed and whether
  any money moved that shouldn't have.
- Run an **out-of-band reconciliation** against the processor to confirm no
  unauthorized disbursements settled; any that did become discrepancies to
  reverse per
  [08 — Payouts and Reconciliation §6.3](08-payouts-and-reconciliation.md#63-discrepancy-handling).

### 10.4 Eradicate and recover

- Fix the root cause (patch, config, revoked access).
- Restore service with rotated secrets and verified-clean state.
- Post correcting ledger entries for any unauthorized movements (never edit
  history — reverse it).

### 10.5 Notify and learn

- **Notify** affected platforms/sellers and regulators within the legally
  required windows (e.g. GDPR 72-hour breach notification for EU personal data).
  Legal/compliance owns the external comms; engineering supplies the facts from
  the audit log and ledger.
- **Blameless post-mortem** with concrete follow-ups. Feed lessons back into
  detection (new leakage-scan rules, new reconciliation checks, tightened access).

## 11. Compliance checklist (for reviews)

- [ ] No code path stores, logs, or transmits a raw PAN/CVV (leakage scan green).
- [ ] Charges reference processor **tokens**, never card data.
- [ ] No PII in any event payload (`payment.*`, `refund.*`, `payout.*`).
- [ ] KYC PII / bank details encrypted with envelope encryption; access
      role-gated and audited.
- [ ] All traffic TLS 1.2+; internal money-path calls use mTLS.
- [ ] Every refund, payout, discrepancy correction, and PII access is in the
      audit log.
- [ ] Console/BFF holds no processor credentials; only the gateway does.
- [ ] Secrets in KMS/secret store; rotation scheduled and auditable.
- [ ] EU seller data resides in-region (EU).
- [ ] Retention windows enforced per data class; deletions logged.

If any box can't be checked, the change is not compliant and must not ship.
Security in a payments company is a gate, not a suggestion.
