> Design/implementation record; verify current behavior against the merged source.
> See [current documentation](../../README.md) and [change status](../../change-status.md).

# Tsukai Consumers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Route authorized native generative work through durable Tsukai jobs while preserving API defaults and domain publication.

**Architecture:** Keep provider policy and transport in `backend/services/ai`. The backend authenticates and prepares immutable scope-bound requests. UI streams through backend; MCP and Mihari submit directly after authorization. Domain publication uses validated durable results, never client-supplied model text.

**Tech Stack:** Python, HTTPX, PyJWT, FastAPI, PostgreSQL, existing React SSE client.

### Task 1: Versioned transport and explicit operation policy

Files: create `backend/services/ai/{client,registry}.py`; test `backend/tests/test_tsukai_client.py`.

- [x] Define default API routing, explicit native task opt-in, credential-owner gate, and unavailable vision/evaluation capabilities.
- [x] Implement POST admission, contiguous replay with Last-Event-ID, deduplication, bounded SSE reconnect, explicit missing-terminal failure, terminal result read and acknowledgement.
- [x] Run `python -m pytest tests/test_tsukai_client.py -q`; expected five passing cases for replay, foreign events, event gaps, missing terminal, and policy.
- [x] Commit and push transport separately.

### Task 2: Central completion facade

Files: create `backend/services/ai/{scope,facade}.py`; modify `backend/services/llm.py`, `backend/mcp_server.py`, `backend/services/text_to_sql.py`.

- [x] Carry owner, caller, effective folder IDs and parent attribution through context variables; sign only after established authorization.
- [x] Enforce root/child recursion policy before provider selection. Reserve metadata child profile exclusively for depth1 text_to_sql with no tools.
- [x] Adapt native results into typed text blocks without claiming unknown token counts are zero. Preserve API return compatibility and default behavior.
- [x] Run existing LLM tests plus facade scope/owner/recursion tests; commit and push.

### Task 3: Direct Mihari execution and conditional publication

Files: modify `backend/routes/mihari.py`, `mihari/mihari.py`; create scoped preparation/publication service and migration.

- [ ] Extract pure request builders and validators in the separately owned maintenance service; never intercept completion calls or reexecute route handlers.
- [ ] Return one exact immutable request plus short-lived task capability. Mihari submits directly to Tsukai, then requests backend domain application by durable job ID.
- [ ] Backend fetches the authenticated durable result and rejects stale source/revision. Record application and review checkpoints atomically with section/document mutations.
- [ ] Keep unchanged-HEAD gating; fresh session on every operation; test failed/blocked tasks never advance checkpoint, duplicate apply is idempotent, newer revisions cannot be overwritten.
- [ ] Commit and push; request coordinator spec review followed by quality review.

### Task 4: Durable UI bridge and authoritative tools

Files: create `backend/services/ai/chat.py`; modify chat routes and MCP authorization/tool instrumentation; frontend changes coordinated separately.

- [ ] Submit one resumable job per agentic/deep turn; plain uses fresh completion. Derive identity, scope and native mapping server-side.
- [ ] Persist canonical messages independently of browser disconnect and reconcile successful unacknowledged jobs after backend restart.
- [ ] Authenticate short-lived tool grants and persist exact results/source references and current scope without hidden reasoning.
- [ ] Preserve existing frontend frame compatibility; add cursor/cancel/replay routes and verify uniqueness, tenant isolation, retrieval/citation evidence, missing-terminal failures.
- [ ] Run targeted regression/integration suites and provide coordinator review evidence before merge.
