# Root access UI implementation plan

> **For agentic workers:** Use superpowers:executing-plans task by task.

**Goal:** Implement the approved Environment & Access interface with real backend APIs and safe write-only credentials.
**Architecture:** Root-scoped routed React/MUI screen; pure validation and API contract module; focused resource dialog and administration sections. Existing AppLayout and folder breadcrumbs remain authoritative.
**Tech Stack:** React19, MUI7, TanStack Query5, TypeScript, Vitest.
**Spec:** /Users/feliperamosdasilva/personal_projects/kioku-vault-spec/docs/superpowers/specs/2026-11-14-central-vault-design.md

## Global constraints
- No secrets in route/search parameters, persistent storage, logs, query cache or reveal UI.
- No simulated data in product; clear pending/error/empty states.
- Root folder ownership is enforced server-side. Descendant shortcuts resolve actual root.
- Responsive grids use minmax(0,1fr), drawers max100vw and wrapped long values.
- Allowed env names `[A-Za-z_][A-Za-z0-9_]*`; loader variables prohibited; guide64KiB; name120; aliases20x120.

## Review focus
- Wrong root or navigation while request completes: stale data must not be saved into another root.
- Credential errors must not echo submitted values or arbitrary provider payload.
- Shared resource environment mismatch must be rejected before mutation.
- Narrow screens and long names must not create horizontal page overflow.
- Revoked devices and stale revisions must render safe recoverable errors.

### Task1: Contract, validation and folder entry
Files: frontend/src/lib/rootAccess.ts, rootAccess.test.ts, App.tsx, DocumentsPage.tsx, AppLayout.tsx.
Interfaces: GET /api/root-access/{root} yields RootAccessCatalog as confirmed by backend agent; mutation methods follow agreed contract. Page /folders/:rootId/access.
- [x] Write validation tests for variable names, ambiguous mappings, aliases, fields and secret-safe errors; run RED.
- [x] Implement validators and typed API functions without secret caching.
- [x] Add routed entry and root/descendant buttons.
- [x] Run tests and typecheck, commit.

### Task2: Resource catalog, binding and credential dialogs
Files: frontend/src/pages/RootAccessPage.tsx, frontend/src/components/access/ResourceDialog.tsx, access.css.
Interfaces: RootAccessCatalog, safe mutation callbacks, resource/binding IDs and revisions.
- [x] Write interaction tests for search/filter, invalid mapping, hidden/discarded secret, correct environment binding and empty/error states.
- [x] Implement approved resource list, side notes, responsive drawer, forms, exact binding selection and dedicated credentials save.
- [x] Run interaction tests/typecheck/lint, commit.

### Task3: Guide, environments, devices and activity
Files: frontend/src/components/access/AccessAdministration.tsx, RootAccessPage.test.tsx.
Interfaces: Aggregate metadata plus guide/environment/device/grant/enrollment APIs.
- [x] Write tests for safe Markdown, guide revision, environment validation, device revoke and grant selection.
- [x] Implement tabs and API mutations, safe feedback and enrollment approval route state.
- [x] Run frontend suite/lint/build, commit.

### Task4: Browser acceptance and final review
- [ ] Test approved catalog/dialog/guide and root entry in isolated browser against backend integration when available.
- [ ] Test mobile390px and long resource/variable text; no viewport overflow.
- [ ] Review whole diff and parent independent review; correct important failures with regression tests.
- [ ] Push PR with measured checks and limitations; no deploy in UI subtask.

## Progress
- UI implementation commit62a49da. Focused15 tests passed; full frontend345/345, lint/typecheck/build passed.
- Browser mocked-catalog acceptance passed desktop1512, widths1024/720/390, long names, resource drawer and guide; no JS errors or horizontal overflow. This is frontend acceptance only, not live backend integration.
- Concurrent guide edit regression observed RED, fixed and focused8/8 passed. Preserve draft base revision and do not remount on aggregate refresh.
- Pending parent independent review and real backend integration before deployment.
