# Vault V2 Product UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver the approved resource-first credential UI without exposing stored values or widening existing grants.

**Architecture:** Add typed credential and usage metadata to the existing catalog while preserving legacy bindings. Separate resource editing, write-only credential editing, usage recipes, and access grants into focused components; use existing bounded, cancellable access requests.

**Tech Stack:** React 19, MUI 7, TypeScript, TanStack Query, Vitest, Playwright.

**Spec:** ../specs/2026-11-14-resource-credentials-v2-design.md (approved design worktree).

## Global Constraints
- 15-second total requests, no automatic write retries, owner-scoped catalog cache, no values in caches/storage/errors.
- Credential values remain component-local and clear after submit/failure/navigation/unmount.
- Preserve V1 binding access and explicit legacy variants; never merge by environment name.
- Shared resources have one new credential and require neither account nor region.
- Match approved drawer tabs and direct environment Add/Replace actions.

## Review Focus
- Long names and action labels at 390/720/1024/1512 widths.
- Timed-out writes require metadata refresh/reconciliation before retry.
- Legacy variants must remain separately identifiable.
- Raw argv requires explicit risk acknowledgement and grant capability.
- Recipe metadata contains selectors and nonsecret template content, not credential values.

## Tasks
- [x] Add additive AccessCredential, AccessUsage, AccessUsageGrant and recipe union contracts to rootAccess.ts, with safe validators and tests for invalid inputs.
- [x] Retain existing ResourceDialog as LegacyResourceDialog; implement resource-first drawer and write-only CredentialEditor. Direct Add creates metadata before value, replacement CAS, pending reconciliation; tests verify no mapping prerequisite and draft clearing.
- [x] Implement UsageEditor for env/argv/config/SSH, exact credential fields and safe destination selectors. Tests cover unsafe names, missing pins, raw argv acknowledgement.
- [x] Add explicit per-recipe device grant controls and legacy access visibility, retaining administration enrollment/revocation.
- [x] Update catalog availability/status from credential metadata and fix responsive grid/row wrapping; no right aside or layout jump.
- [x] Run targeted tests, full frontend suite/lint/TypeScript/build and isolated browser responsive tests. Open PR for root review; no direct deployment.

## Verification
- 53 frontend test files, 396 tests passed using synthetic Supabase test configuration.
- TypeScript and production build passed. ESLint: zero errors, one existing ErrorBoundary warning.
- Actual React drawer rendered in isolated Chrome with synthetic metadata: 28 view/viewport combinations, zero horizontal overflow or page errors. Backend write integration remains parent-coordinated before release.
