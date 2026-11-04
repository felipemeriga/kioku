> Design/implementation record; verify current behavior against the merged source.
> See [current documentation](../../README.md) and [change status](../../change-status.md).

# Mihari Direct Tsukai Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Run repository maintenance directly from Mihari through Tsukai while keeping source authorization and checked publication in the backend.

**Architecture:** Pure operation builders and validators consume immutable backend snapshots. Authenticated preparation binds the exact runner request to owner/repository/HEAD/revision; backend publication fetches the durable result and applies it under a SQL transaction with revision comparisons and job deduplication. The native path is owner-only and disabled by default; API routes share the same operation pipeline.

**Tech Stack:** Python, FastAPI, requests/httpx, PostgreSQL/Supabase, canonical Tsukai v1 JSON.

### Task 1: Extract operations

- [x] Create `backend/services/maintenance/operations.py` with pure `build_request(snapshot)` and `validate_result(snapshot, raw)` for review_plan, activity, how_it_runs, deployment, reground, documentation and learnings.
- [x] Keep evidence and source schemas explicit; reject unknown fields, malformed types, unsupported source IDs, thin outputs and non-completed outcomes.

### Task 2: Prepare and publish

- [x] Create `snapshots.py` and `execution.py` for backend-authorized snapshots, immutable durable preparations, request-bound capabilities and server-side result retrieval.
- [x] Add `20261104140000_mihari_prepared_execution.sql` for transaction-based revision checks, unique job publication, learning checkpoints and complete review-pass acknowledgements.
- [x] Route existing API generation through shared builders/validation/publication with API as the default provider.

### Task 3: Direct caller

- [x] Add explicit `maintenance_post` call sites in `mihari/mihari.py`. Prepare through backend, submit inference directly to Tsukai, poll durable result, then publish only job ID through backend.
- [ ] Verify contract, stale revisions, duplicate publication, auth denial, missing input and existing fixture behavior; format, commit, push and open draft PR for parent review.
