# Tsukai Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable, private native subscription runner with fresh completion calls and explicit resumable chat.

**Architecture:** PostgreSQL owns accepted jobs, attempts, events, conversation mappings, leases and result acknowledgements. One scheduler claims at most two root processes plus a reserved metadata child; Redis is optional wake-up only. Native Claude CLI owns subscription execution and native session storage; domain publication remains with authorized consumers.

**Tech Stack:** Python3.12, FastAPI, SQLAlchemy async Core, asyncpg, PyJWT, JSON Schema, native Claude2.1.285.

---

### Task1: Canonical contract
**Files:** `tsukai/src/tsukai/protocol.py`, `tsukai/protocol/*.schema.json`, `tsukai/protocol/README.md`.
- [ ] Define strict request/capability/event/completion models; forbid native IDs and raw tool URLs.
- [ ] Generate schema via `JobRequest.model_json_schema()` and equivalent models.
- [ ] Validate profile/depth/freshness/owner and idempotency conflict fixtures.
- [ ] Commit `feat: define Tsukai execution protocol`.

### Task2: Durable admission and ownership
**Files:** `tsukai/src/tsukai/{tables,store}.py`, `supabase/migrations/20261104090000_tsukai_execution.sql`, `tsukai/tests/test_store.py`.
- [ ] Create jobs, attempts, events, sessions, locks and acknowledgements tables with unique constraints and RLS denying client access.
- [ ] Implement transactionally admitted idempotency, conversation lock, skip-locked claim, fencing lease heartbeat, contiguous per-job event sequences and result/ack atomicity.
- [ ] Exercise duplicate concurrent admission, changed payload conflict, same-chat exclusion, expired lease uncertainty, replay across store recreation and ack conflicts.
- [ ] Commit `feat: persist Tsukai jobs events and session ownership`.

### Task3: Native adapter
**Files:** `tsukai/src/tsukai/{native,validation,usage}.py`, `tsukai/tests/test_native.py`, `tsukai/tests/fixtures/native_cli.py`.
- [ ] Launch actual CLI with environment allowlist, explicit read-only MCP, no built-in shell/files/tools/hooks/user instructions, bounded NDJSON decoder and process-group cancellation.
- [ ] Normalize provisional deltas, use terminal result as canonical text, validate strict operation output, reject interaction requests and record incomplete usage.
- [ ] Test native-shaped fixture process, no secret leakage, fresh repair IDs, resume args only from durable mapping, stderr flooding, missing results and timeouts.
- [ ] Commit `feat: execute bounded native subscription attempts`.

### Task4: Scheduler and HTTP service
**Files:** `tsukai/src/tsukai/{config,auth,scheduler,app}.py`, `tsukai/tests/test_app.py`.
- [ ] Require service bearer plus dedicated signed owner/scope capability and entitled owner allowlist; reject nested roots and allow only registered depth1 metadata child.
- [ ] Poll SQL queue with fairness, two roots/one child/one maintenance, durable cancellation, bounded retry and single fresh schema repair.
- [ ] Implement replay SSE, result fetch and reconciliation ack; instrument authoritative backend tool events; cached auth readiness, single probe, quota/auth circuits and120s drain.
- [ ] Test acceptance→disconnect→terminal→replay, crash recovery, cross-owner denial, metadata reserved lane, auth circuit and cancellation.
- [ ] Commit `feat: serve durable Tsukai execution and replay`.

### Task5: Acceptance and integration handoff
**Files:** `tsukai/tests/*`, `tsukai/protocol/README.md`.
- [ ] Run `uv run --project tsukai pytest tsukai/tests -q` and `uv run --project tsukai ruff check tsukai` / `ruff format --check tsukai`.
- [ ] Run PostgreSQL integration tests when local or server fixture database is available, with no production domain writes.
- [ ] Hand backend/deploy agents exact schema/config and test evidence; parent arranges independent spec and quality review before merging.
- [ ] Keep flags off pending real personal-owner deployment probe, production retrieval fidelity and native expiry/rotation gates.
