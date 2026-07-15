# Final-Fixes Report — CLI browser-handoff login feature

Date: 2026-07-15  
Branch: feat/notion-sync

---

## Issue 1A — Token poll rate headroom (backend)

**Problem**: `_device_rate_limit` used a single `_DEVICE_RATE_MAX=10` bucket for all endpoints, including `/token`. The CLI polls every 2s (~30/min), so a 429 fires ~20s into a normal login.

**Fix** (`backend/routes/cli.py`):
- Added `_DEVICE_TOKEN_RATE_MAX = 60` constant.
- `_device_rate_limit` now selects `limit = _DEVICE_TOKEN_RATE_MAX if bucket == "token" else _DEVICE_RATE_MAX`.
- Existing `test_start_rate_limited_after_burst` still passes because it monkeypatches `_DEVICE_RATE_MAX` and tests the `"start"` bucket path.

**New test** (`backend/tests/test_cli_auth.py`):
- `test_token_poll_not_rate_limited_within_headroom`: fires 35 consecutive `/token` polls, asserts none returns 429. All return 410 (unknown code).

**Verify**: `uv run pytest tests/test_cli_auth.py -v` → 13/13 passed.

---

## Issue 1B — Resilient devicePoll (CLI)

**Problem**: `devicePoll` catch-all `else → expired` mapped 429 and network errors to terminal "expired" state, aborting the login.

**Fix** (`cli/src/lib/api.ts`):
- Wrapped `fetch` in try/catch; network errors → `{ status: "pending" }`.
- Explicit mapping: 200 → authorized, 428 → pending, 403 → denied, 410 → expired, 429 or 5xx → pending (transient/keep waiting), any other status → expired (terminal).

**Verify**: `cd cli && npm run build` → zero errors.

---

## Issue 2 — Stale OTP help text

**Fix** (`cli/src/index.ts`):
- Changed `# sign in with email + OTP` → `# sign in via browser` in the global examples block.

**Fix** (`backend/routes/cli.py`):
- Removed the `_anon_client` function entirely (which contained the only "magic-link, verify OTP" comment).

**Verify**: `grep -rn "sendOtp\|verifyOtp" cli/src` → empty.

---

## Issue 3 — Dead code removal (backend)

**Confirmed no callers**: `grep -rn _anon_client backend/routes backend/` → only the definition in cli.py itself.

**Removed**:
- `_anon_client()` function and its docstring.
- `from supabase import create_client` import.
- `from pydantic import BaseModel, EmailStr, Field` → `from pydantic import BaseModel, Field` (EmailStr was unused).

Also removed pre-existing unused imports discovered during ruff run:
- `import json as _json` in `session_capture`.
- `MemoryCategory` from `services.mem0_sync` import in `session_capture`.

**Verify**: `uv run ruff check routes/cli.py --select E501,F401` → all checks passed.

---

## Issue 4 — E501 long line in `_client_ip`

**Fix** (`backend/routes/cli.py`):
- Split the one-liner ternary into an if/return block.

**Verify**: `uv run ruff check routes/cli.py --select E501` → all checks passed.

---

## Issue 5 — `_client_ip` comment on trusted proxy assumption

**Fix** (`backend/routes/cli.py`):
- Added two-line comment above the fwd logic: "Trusts X-Forwarded-For; assumes a trusted reverse proxy sets it. The limiter is DoS-dampening, not a security boundary."

---

## Issue 6 — Frontend test fixes (`CliAuthPage.test.tsx`)

**Fix 1 — `deviceInfo` in beforeEach**:
- Extracted `deviceInfo` mock into a named `vi.fn()` variable.
- Added `deviceInfo.mockClear()` and reset in `beforeEach`.

**Fix 2 — Unauthenticated redirect test**:
- Changed `useAuth` mock to use a `vi.fn()` (`mockUseAuth`) so individual tests can override it.
- Added test `"redirects unauthenticated users to /login with redirect param"`:
  - Mocks `useAuth` to return `{ session: null, loading: false }`.
  - Renders within a `MemoryRouter` + `Routes` with a `/login` sentinel element.
  - Asserts `login-sentinel` appears after the `<Navigate>` redirect fires.

**Verify**: `npx vitest run src/pages/CliAuthPage.test.tsx` → PASS (3). `npx tsc --noEmit` → no errors.

---

## Remaining ruff issues (pre-existing, not in scope)

These were present before this changeset and are not E501/F401:
- `I001` (import ordering) in `mint_api_key`, `session_capture`, `search` functions' local imports.
- `F841` (unused variable `sb`) in `mint_api_key`.

---

## Verify command outputs

```
pytest tests/test_cli_auth.py -v         → 13/13 passed
ruff check routes/cli.py --select E501,F401  → all checks passed
cd cli && npm run build                  → zero errors
grep -rn "sendOtp|verifyOtp" cli/src     → (empty)
npx vitest run src/pages/CliAuthPage.test.tsx → PASS (3)
npx tsc --noEmit                         → no errors
e2e_cli_login.py                         → 10/10 checks passed
```
