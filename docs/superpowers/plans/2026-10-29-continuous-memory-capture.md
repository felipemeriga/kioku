# Continuous Memory Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture Claude Code session records through the existing Manabi WebSocket and durably acknowledge them into a raw holding table without changing session behavior.

**Architecture:** Manabi reads only Claude JSONL files for repositories already bound in its inventory, persists outbound events locally, and sends one event at a time over the authenticated remote WebSocket. Backend validates ownership and payload, encrypts the original with an AES-GCM data key wrapped by existing AWS KMS, inserts event plus HOLDING row in one SQL transaction, then acknowledges. Mihari processing remains disabled until its separate slice.

**Tech Stack:** TypeScript/Node CLI, FastAPI/Pydantic, Supabase Postgres RPC, AWS KMS, cryptography AESGCM, launchd/systemd/Windows existing Manabi service.

---

## Task 1: Raw event schema and atomic accept RPC

**Files:** Create `supabase/migrations/20261029000000_agent_memory_holding.sql`; test via `backend/tests/test_memory_holding.py` using local Supabase when available.

- [ ] Define `memory_raw_events` with `(user_id,event_id)` primary key, owned `folder_id`, `machine_id`, source/session/position/times/provenance, encrypted original, redacted text and hash; `memory_holding` with one queued row per raw event. Enable RLS, revoke direct client access.
- [ ] Add `accept_memory_event` SECURITY DEFINER RPC. Verify machine owner and folder owner/repository binding in SQL; insert both rows transactionally; return `stored` or `duplicate`; same ID/different hash raises a typed conflict. Fix search path and grant execute only to service role.
- [ ] Test duplicate, hash conflict, cross-user folder, cross-machine, and rollback on holding failure against local database. Commit schema separately.

## Task 2: Encryption and WebSocket contract

**Files:** Create `backend/services/agent_memory/crypto.py`, `backend/services/agent_memory/ingest.py`; modify `backend/routes/remotes.py`; add `backend/tests/test_memory_ingest.py`.

- [ ] Write failing tests for Pydantic validation, secret redaction, KMS error, duplicate ack, scope denial and storage error. Existing heartbeat/inventory tests must remain green.
- [ ] Generate an AES-256-GCM data key locally, wrap only that key with KMS using `KIOKU_KMS_KEY_ID` and context `app=kioku`, encrypt the full event, and derive a redacted copy for processing. No plaintext in logs or DB.
- [ ] Add `memory_post` after authenticated `ready`, with 64 KiB cap, model validation, owner binding, `accept_memory_event` RPC, and `memory_ack` only after success. Recoverable failure returns `memory_nack` with retry. Advertise `memory_post_v1` in `ready`; do not alter legacy heartbeat/inventory behavior.
- [ ] Run targeted tests, Ruff check/format, and commit backend code.

## Task 3: Manabi durable capture and delivery

**Files:** Create `cli/src/lib/manabi-memory-source.ts`, `cli/src/lib/manabi-memory-spool.ts`; modify `cli/src/lib/manabi-client.ts`; add `cli/src/lib/manabi-memory.test.ts`.

- [ ] Write failing tests for bound-project discovery, JSONL incremental read, incomplete line, truncation/rotation, event-ID stability, spool restart, duplicate ack, nack retry and disconnected operation.
- [ ] Read only Claude Code JSONL for bound repository paths; preserve record content/position and provenance. Stage complete records atomically in an 0600 local spool with a byte cap; never advance source position before staging.
- [ ] Send pending events only when server `ready` advertises `memory_post_v1`; cap in-flight messages and retry on reconnect. Remove each event from spool only after matching `memory_ack`. Keep event collection independent of WebSocket readiness and never block an agent session.
- [ ] Run CLI tests, ESLint/Prettier, and commit CLI code.

## Task 4: Integration gate

**Files:** Extend `backend/tests/test_remotes.py`, `cli/src/lib/manabi-reliability.test.ts`; no additional production code unless a test exposes a defect.

- [ ] Exercise old Manabi against new backend and new Manabi against backend without capability; both must retain presence/inventory behavior.
- [ ] Simulate close after database commit before ack, then reconnect/replay; assert exactly one raw row and one HOLDING row.
- [ ] Verify invalid owner and oversized payload never create a row; a DB/KMS outage leaves the local spool intact.
- [ ] Run backend and CLI suites, confirm migration applies locally, push branch, open PR. Keep capture feature disabled by default until schema/backend precede the released CLI.

## Subsequent slices

Lifecycle/Judge, ACTIVE index and MCP retrieval, Living Summary, and UI/history each receive separate plans and PRs under the merged technical design. The capture slice is independently testable: it preserves evidence safely without publishing unjudged memories as facts.
