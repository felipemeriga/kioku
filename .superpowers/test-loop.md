# kioku feature test loop — ledger

## Iteration 1 (repo: Chat / sigmaSd/Chat)
- init --yes → BUG: blocked on root picker (multiple roots, no owner match). FIXED 027e6c8.
- summary save → BUG: needs_generation stuck True (4-digit microsecond timestamp fromisoformat fail). FIXED (robust _parse_iso).
- Verified: init wires folder+key+hook(settings.local.json); no-summary→needs_generation=true; PUT briefing 200; after→needs_generation=FALSE + sections in folder-summary + UI /briefing endpoint.
- Tested features: init --yes, hook location (settings.local.json), folder-summary needs_generation, briefing save→UI reflect.
- NOT yet tested: interactive existing-vs-new folder prompt, real background-claude autogen E2E, documentation abstract + get_repo_documentation (needs repo_documentation migration), doctor, live git activity content, existing-folder reuse.

## Iteration 2 (repo: Emberblast / felipemeriga)
- init --yes: works (root fix confirmed: "Using root ... (default)").
- doctor: ALL checks pass — config, backend, login token, MCP, .mcp.json, SessionStart hook (settings.local.json ✓), CLAUDE.md, state. No bug.
- live activity: injects REAL commits + branch (feat/textual-tui). ✓
- background autogen: LAUNCHED ✓ — session-start printed "generating in background" note, created lock, claude -p (detailed prompt) running as detached process. Real subscription generation in progress.
- NO new bugs this iteration.
- TODO next: verify Emberblast summary APPEARED (autogen completion) in folder-summary + UI; then test documentation flow (needs repo_documentation migration), interactive existing-vs-new prompt, existing-folder reuse.

## Iteration 3 (repo: Emberblast — autogen completion + existing-folder reuse)
- Emberblast background autogen COMPLETED end-to-end ✓ — needs_generation=FALSE, all 8 sections filled (activity + 7 Claude-authored). Log shows GROUNDED output: real file paths (__main__.py, game_orchestrator.py…), real run/test commands, and it flagged 2 real repo findings (CI runs only a 4-file test subset; Dockerfile stale python:3.8 vs pyproject). Detailed generateInstruction prompt is working — output is repo-specific, not generic.
- existing-folder reuse ✓ — re-init --yes → "Attaching to existing repo Emberblast" → SAME folder_id (no duplicate created).
- UI /briefing data path ✓ — all 8 sections have structured content (overview.purpose is a real Emberblast description).
- NO new bugs this iteration. Core flow (init → no-summary → background autogen → grounded save → needs_generation=false → folder-summary + UI) fully validated.
- STILL not tested: documentation deep-doc flow (blocked on repo_documentation migration — stale DB password), interactive existing-vs-new folder PICKER (only --yes path exercised so far).

## Iteration 4 (repo: restful-rust / blurbyte — RUST language generality)
- Purpose: prove the flow generalizes beyond Python/JS to a Rust project.
- init --yes ✓ — detected blurbyte/restful-rust, created folder, wired mcp/hook/CLAUDE.md/gitignore.
- doctor ✓ — all checks green (config, backend, login, MCP, .mcp.json, SessionStart hook in settings.local.json, CLAUDE.md, state).
- folder-summary BEFORE ✓ — needs_generation=True, section_order = 7 stable sections.
- session-start ✓ — printed "generating in background" note; launched autogen (lock + claude -p PID); activity injection showed REAL Rust commits (branch master, full history, uncommitted changes M/??) live from clone, no LLM.
- autogen completion ✓ — finished in ~230s, needs_generation flipped to False, all 8 sections filled. Output correctly identified a Warp-based Rust CRUD API: overview.purpose accurate, important_files cites real Rust paths (src/routes.rs) with grounded roles. UI /briefing shows all 8 sections.
- RESULT: full flow (init → no-summary → background autogen → grounded save → needs_generation=false → folder-summary + UI) validated on RUST — proves language generality (previously only Python/JS). NO bugs found.

## Iteration 5 (EDGE / ROBUSTNESS — varied away from happy path)
- Focus: failure guards + idempotency + hook format + --root flag (happy path already covered 3x across JS/Py/Rust).
- EDGE A ✓ init in a NON-git dir → exit code 1 + clear message ("must be run inside a cloned git repository").
- EDGE B ✓ init IDEMPOTENCY (re-run on already-wired restful-rust): CLAUDE.md kioku block stays 1, .mcp.json kioku entry stays 1, SessionStart=1 + Stop=1 hooks (no duplication).
- EDGE C ✓ hook format in settings.local.json is well-formed GROUPS (matcher/hooks[].{type,command}) — the exact shape whose absence broke Claude Code startup earlier. SessionStart→'kioku session-start', Stop→'kioku capture'.
- EDGE D ✓ --root flag: valid name → explicit "Using root X" binding (not the default ladder); invalid name → clear error "No root folder named ..." + exit 1.
- defi-lending-cli wired + folder-summary queryable (needs_generation=True).
- NO bugs found. All guards/idempotency/format checks pass.
- STILL not tested: interactive existing-vs-new folder PICKER (inquirer TTY — hard to drive non-interactively), deep-doc documentation flow (blocked on repo_documentation migration / stale DB password).

## Iteration 6 (BUG FOUND + FIXED — HIGH IMPACT: multi-repo key revocation)
- Symptom: folder-summary 401 "Invalid or unscoped api key" for restful-rust/Emberblast/Chat; only the most-recently-inited repo's key worked.
- Root cause: api_keys has UNIQUE(user_id, scope_folder_id) and create_api_key DELETEs prior keys for the same scope. CLI scoped keys to the ROOT → all repos under a root share one scope → each `kioku init` revoked every sibling repo's key (their .mcp.json → 401 → SessionStart/Stop hooks + MCP all break). iter5's re-inits triggered it.
- Considered: (A) additive keys — BLOCKED (unique constraint; DDL needs the un-appliable migration). (B) root-scope + client key cache — stateful, staleness edge cases. (C) repo-scope the key — chosen: clean, migration-free, respects the constraint. validate_scope_folder allows sub-folder scopes; _descendant_folder_ids is inclusive so a repo-scoped key reads its own briefing.
- Fix (commit 01e3b7b): init.ts scope_folder_id rootId→repoFolder.id + CLAUDE.md orientation note updated. CLI rebuilt; 11/11 CLI tests pass.
- Regression-verified: 2 repos under 1 root both keep valid keys (200) after sequential inits (was 401 for the first). Restored Chat/Emberblast/restful-rust via re-init — all load full briefings (7-8 sections). Cross-repo drill via single root key deferred to v2 (already was).

## Iteration 7 (repo: kubernetes-go-grpc / shuza — GO + validate write path under repo-scoped key)
- Purpose: confirm a REPO-scoped key (iter6 fix) can WRITE a briefing via MCP replace_folder_briefing (prior repos were generated pre-fix with root keys). Also adds Go as a language.
- init --yes ✓ — key confirmed REPO-scoped (scope_folder_id == repo folder_id ccf8a7c5, not the root).
- key hygiene ✓ — 7 keys total, each a distinct scope, ZERO scopes with >1 key (repo-scoping = clean 1-key-per-repo, no sprawl).
- session-start ✓ — launched autogen, injected live Go git activity (branch master, real commits).
- INFRA EVENT: backend (:8000) + MCP (:8001) background tasks were KILLED mid-run (frontend survived). Restarted both from backend/.venv (uvicorn main:app :8000; python mcp_server.py :8001) — health green again. The in-flight claude -p autogen (PID 29529) survived the MCP outage; re-polling for write completion after restore.
- autogen write completion ✓ — repo-scoped key WROTE the briefing via MCP replace_folder_briefing (needs_generation=False). All 8 sections filled, grounded Go content ("Go gRPC microservices … deploy to Kubernetes", real paths). API + UI both show 8 sections. CONFIRMS iter6 fix works for the WRITE path, not just reads.
- RESULT: repo-scoped keys fully validated E2E (read + write) on a Go repo. Service outage recovered (backend+MCP restarted). NO new bugs.

## Iteration 8 (CAPTURE / Stop-hook subsystem — previously untested end-to-end)
- Built a realistic 6-turn Claude Code JSONL transcript; piped a Stop-hook payload to `kioku capture`.
- CLI capture ✓ — parsed transcript, computed delta, first-capture turn-threshold logic fired ("firing capture: 6 turns"), POSTed with the REPO-scoped key (iter6 fix works for capture auth too), updated state, exit 0.
- On kubernetes-go-grpc → response {ok:true, skipped:true, reason:"Mem0 not wired for this folder"}. NOT a bug: Mem0 is a per-folder lazy opt-in (empirically only 1 mem0_sync_configs row exists, on the 'agentic-rag' folder). get_client_for_folder exact-matches root_folder_id==folder_id; capture correctly skips unwired folders. The init "captures learnings to Mem0" copy is conditional but functionally correct.
- FULL distill→Mem0 path ✓ (against the Mem0-wired agentic-rag folder, owner-matched): capture returned count=3, correctly categorized preference/decision/issue, each saved to Mem0 (status SUCCEEDED, proper folder scoping + dedup metadata). Cleaned up: 3 test memories deleted, test api-key revoked.
- Token hygiene finding: the CLI's cached UI access_token expires ~1h; out-of-band curl with $TOK fails once expired, but `kioku init`/whoami auto-refresh via refresh_token → Supabase /auth/v1/token (verified: init on todo-api-pf refreshed the token + minted). So CLI ops are unaffected; only my raw-curl UI checks need the CLI to refresh first.
- Also inited todo-api-pf (fresh) as the refresh/mint live-test. NO bugs found. Stack healthy throughout (after iter7 restart).

## Iteration 9 (STALENESS / TTL regeneration — the auto-regen deadline contract)
- Validated _needs_generation (SUMMARY_TTL_DAYS=7) end-to-end by backdating restful-rust's folder_summaries.generated_at and hitting /api/cli/folder-summary (needs_generation is derived at READ time):
  - baseline (fresh) → False ✓
  - 8 days old → True ✓ (TTL exceeded → would re-trigger autogen)
  - 6 days old → False ✓ (within TTL)
  - 7d+1min → True ✓ (boundary correct)
  - originals restored → False ✓ (clean, no data pollution).
- Confirms the "regenerate only when the 7-day deadline is reached" design.
- UI /briefing data path re-verified: all 8 sections render.
- doc migration STILL NOT APPLIED: repo_documentation table missing (PGRST205). The endpoint's doc_needs_generation=True is just the try/except default when the table is absent; it does NOT mean the doc flow works. save_repo_documentation would fail until the user applies supabase/migrations/20260716130000_repo_documentation.sql. (Can't apply via PostgREST client — needs psql/SQL editor / supabase db push.)
- NO bugs found. Stack healthy.

## Iteration 10 (LIVE MCP tool interface — the real Claude Code ↔ kioku path)
- Connected a real MCP client over SSE (http://localhost:8001/sse) with the restful-rust REPO-scoped key (iter6 fix works over MCP too, not just REST).
- list_tools ✓ — get_folder_briefing, update_folder_briefing_section, replace_folder_briefing all exposed.
- get_folder_briefing ✓ — returned the full 9575-char briefing (all sections).
- update_folder_briefing_section(section='preferences', pin=True) ✓ — returned "Updated section 'preferences' (status=pinned)". Persisted correctly: creates a NEW versioned folder_summaries row (provenance=agent_mcp), which becomes the latest so folder-summary/get_folder_briefing reflect it.
- PIN verified ✓ — the section envelope stores status='pinned' (NOT a `pinned` bool; my first check looked at the wrong field → false alarm, no bug).
- Observation (not a bug): each update_folder_briefing_section call writes a new full-content row (versioned history). Rows accumulate per section-update; folder-summary always reads latest so it's correct, but there's no pruning.
- Cleanup: deleted the test row; restful-rust reverted to its real briefing (8 sections, 1 row, needs_generation=False). No pollution left.
- NO bugs found. Stack healthy.

## Iteration 11 (ACTIVITY INJECTION — "live git changes since last session" delta)
- Tested composeActivity/gitActivity (cli/src/lib/git-activity.ts) against a controlled temp git repo (4 commits at fixed dates day4..day1 + 1 untracked file):
  - NO since → all 4 commits (newest first) + "?? dirty.txt" working change ✓
  - since=2026-07-11T18:00 → correctly returns ONLY day2+day1 (excludes day4 @07-10 and day3 @07-11T12:00, includes day2 @07-12 and day1 @07-13). Since-boundary filtering exact ✓
  - branch name shown ✓
- Watermark round-trip (restful-rust) ✓ — session-start reads last_session_at, injects activity, then stamps a fresh last_session_at (advanced 02:14→03:24).
- No-new-activity case ✓ — a 2nd session-start right after shows Branch + Uncommitted working changes but OMITS the empty "Recent commits" list (nothing since the fresh watermark). Correct.
- NO bugs found. Stack healthy.

## Iteration 12 (INTERACTIVE folder picker — last untested user-facing feature)
- Drove `kioku init --root clone-test-1783355081` (NO --yes) via a Python PTY on the fresh image-to-ascii repo (pre-created a matching child folder 28d6b3b5 so the name-match default is deterministic).
- Picker ✓ — rendered "? Which folder does this repo bind to?" with the top/default option "image-to-ascii (matches your repo name — recommended)" + nav hint "↑↓ navigate • ⏎ select".
- Sending Enter selected the recommended name-match → "Attaching to 'image-to-ascii'" → attached to the EXISTING folder 28d6b3b5 (exact id match), NOT a new one. Validates the "select an existing folder" interactive path.
- Wired correctly: folder-summary queryable (needs_generation=True, fresh), and the minted key is scoped to the REPO folder (iter6 fix holds through the interactive path too).
- NO bugs found. Stack healthy.
- REMAINING untested: only the deep-doc documentation flow (still blocked on repo_documentation migration).
