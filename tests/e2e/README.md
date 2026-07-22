# E2E Test Suites

Comprehensive end-to-end tests for the agentic-rag stack — REST, MCP, CLI, and full multi-user workflows.

## Running

### Everything

```bash
# From the repo root, with backend + MCP up:
tests/e2e/run_all_e2e.sh
```

### One suite by filter

```bash
tests/e2e/run_all_e2e.sh --only briefing
tests/e2e/run_all_e2e.sh --only "CLI GitHub"
```

### List what would run without executing

```bash
tests/e2e/run_all_e2e.sh --list
```

### Prerequisites

- Backend up at `http://localhost:8000/api/health`
- MCP up at `http://localhost:8001/health` (for MCP suites)
- `felipe.meriga@gmail.com` seeded in Supabase (the primary test account)
- Env vars available (loaded from `backend/.env`)

## Suites

| Suite | What it covers |
|---|---|
| REST sanity walk | 45 endpoints across auth, folders, docs, chat, integrations |
| Cross-user isolation | 21 probes proving user 2 can't read/write user 1's data |
| Deep bug hunt round 1 | Cascade delete + concurrency + edge inputs |
| Deep bug hunt round 2 | Focus resolver edge cases, briefing cascades, workspace rollup |
| Chat + SSE | Streaming end-to-end incl. disconnect resilience |
| MCP + detail page | MCP tool surface + Playwright UI walk |
| Claude Code first session | Full session simulation via real MCP over SSE |
| Dedup Mem0 | Same content 3× = 1 memory, paraphrase = 2 |
| Multi-type file viewer | pdf / image / md / txt / json render inline |
| Focus folder | Root-scoped key + drill-into-subrepo |
| Persona: UX Playwright | Automated UI regression sweep |
| Persona: Developer with Claude Code | Session start → update briefing → PC switch |
| Persona: Bug hunter | Adversarial: quotas, huge payloads, malformed data |
| Dev workflow | Real MCP + Mem0 mutation across sessions |
| Briefing lifecycle | ⭐ Full 33-check lifecycle: MCP replace, section edits, resets |
| CLI capture (Stop hook) | Threshold + transcript delta + Mem0 write |
| CLI smoothness | Smart defaults + fallback menu |
| CLI GitHub auth ladder | gh CLI → env var → PAT paste chain |
| CLI pro tier | Auto-refresh, --json, NO_COLOR, briefing/ls/logout |
| CLI (full lifecycle) | init → session-start → status → rerun idempotent |

## Adding a new suite

1. Write `/tmp/e2e_your_test.py` (or `tests/e2e/e2e_your_test.py`) — use `httpx`, print `PASS: N pass, M fail` at the end.
2. Add a line to the `SUITES` array in `run_all_e2e.sh`:

   ```bash
   "Your test name:/tmp/e2e_your_test.py"
   ```

3. Test the filter: `run_all_e2e.sh --only "Your test"`

## Known flakes

- **Supabase OTP rate limit** — some suites re-issue OTPs within 50s of each other and hit Supabase's rate limit. Not a bug; suites retry.
- **Anthropic slowness** — parallel-regenerate probes occasionally hit `ReadTimeout` when Anthropic is slow. Retry.

## Results directory

Each run writes logs to `/tmp/e2e_results_<timestamp>/` — one `.log` per suite. Failed suites print their tail in the summary; use the log file for the full trace.
