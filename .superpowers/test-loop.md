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

## Iteration 13 (direct MCP write tools — replace_folder_briefing + scope tools)
- doc migration STILL not applied (repo_documentation table missing). Can't apply DDL via PostgREST client — needs user's psql/SQL editor.
- Via live MCP session (image-to-ascii repo-scoped key):
  - get_folder_briefing_schema ✓ — returned the 9-section schema + authoring notes.
  - replace_folder_briefing ✓ — wrote all 7 stable sections in one call → {ok:true, replaced:[7]}. This is the exact tool the background autogen uses; here exercised directly (a full "trigger summary via the tool path + verify" cycle without the slow autogen).
  - list_folders_in_scope ✓ — returns ONLY the repo's own folder subtree (scope_folder_id=28d6b3b5), confirming repo-scoping limits visibility correctly.
  - get_folder_orientation ✓ — 7183 chars, mentions image-to-ascii.
- Verified: folder-summary needs_generation→False, 8 sections, overview.purpose stored correctly; UI /briefing shows all 8. 
- NO bugs found. Stack healthy.

## Iteration 14 (BUG FOUND + FIXED — HIGH IMPACT: .mcp.json missing type:sse broke ALL kioku MCP tools)
- Full E2E on a Solidity DeFi repo (defi-lending-contract). init + activity fine, but the autogen claude -p EXITED WITHOUT WRITING (needs_generation stayed True).
- Root cause (from the autogen's own log): `.mcp.json` kioku entry was `{url,headers}` with NO `"type"`. Claude Code parses a typeless entry as a stdio server ("command: expected string, received undefined") and SILENTLY SKIPS kioku → none of its MCP tools register → the autogen couldn't call get_folder_briefing_schema/replace_folder_briefing, and every in-session tool call would fail too. (Likely surfaced by a Claude Code version bump mid-loop — earlier autogens on the same format had succeeded.)
- Fix (commit): backend mint mcp_config now emits `"type":"sse"` (cli.py), AND the CLI writeMcpConfig forces `{type:"sse", ...}` on write so re-running `init` REPAIRS older repos. 11/11 CLI tests pass; backend restarted.
- Verified E2E: re-init writes type:sse; fresh backend mint includes it; relaunched autogen WROTE the briefing via MCP in ~70s (needs_generation→False) — grounded Solidity content ("UUPS-upgradeable ... DeFi lending pool ... USDC collateral"), 8 sections in folder-summary + UI.
- Repaired all 6 other wired repos' .mcp.json (Chat/Emberblast/kubernetes-go-grpc/todo-api-pf/image-to-ascii/defi-lending-cli → type=sse).
- Stack healthy.

## Iteration 15 (verify iter14 fix through Claude Code's OWN MCP loader)
- `claude mcp list` in a repaired repo shows: `kioku: http://localhost:8001/sse (SSE) - ⏸ Pending approval` — correctly loaded as an SSE server (pre-fix it was "Skipped — invalid config"). "Pending approval" is the normal new-server gate; the autogen bypasses it via --permission-mode bypassPermissions (which is why iter14's autogen succeeded).
- Airtight before/after contrast through the real parser (temp-strip type, then restore):
  - typeless → "[Warning] [kioku] mcpServers.kioku: Skipped — invalid MCP server config ... command: expected string, received undefined" (the exact bug)
  - type:sse → "kioku ... (SSE) - Pending approval" (loads correctly)
- Confirms the iter14 fix resolves the bug at Claude Code's config-parser level, not just via a direct Python MCP client. .mcp.json restored. NO new bugs. Stack healthy.
- (Note: agentic-rag prod SSE + plugin:github show "Failed to connect" in claude mcp list — unrelated deployed servers, not this work.)

## Iteration 16 (DEEP-DOC DOCUMENTATION FLOW — last blocked feature, migration now applied)
- User applied the repo_documentation migration → table exists.
- Full doc flow via MCP (defi-lending-contract, repo-scoped key):
  - save_repo_documentation(content, abstract) ✓ → {ok:true, doc_chars:533, abstract_saved:true}; inserted 1 repo_documentation row + wrote the `documentation` briefing section.
  - get_repo_documentation() ✓ → returned the full doc (LendingPool.sol + UUPS content).
  - folder-summary ✓ → doc_needs_generation flipped True→False, doc_generated_at set; `documentation` section present with the abstract.
  - session-start injection ✓ → prints "## documentation\n<abstract>\n\nFull architecture docs available — call get_repo_documentation." and the stale-doc OFFER is correctly SUPPRESSED while fresh.
  - staleness ✓ → after deleting the doc, doc_needs_generation reverts to True.
- Cleaned up the test doc (deleted repo_documentation row + the doc-added folder_summaries row) so the repo reverts to its real autogen briefing (8 sections) with no dangling documentation section.
- NO bugs found. Stack healthy.
- MILESTONE: ALL kioku features now validated end-to-end. Two high-impact bugs found+fixed over the loop (iter6 multi-repo key revocation; iter14 .mcp.json missing type:sse).

## Iteration 17 (REAL agent-authored deep-doc generation — not a stub)
- Launched a real deep-doc generation (claude -p, bypassPermissions, KIOKU_NO_AUTOGEN) on defi-lending-contract: "fan out subagents, write a structured architecture doc, save via save_repo_documentation".
- Completed in ~180s. Result is genuinely high quality:
  - 19,786 chars (vs the iter16 hand-authored 533-char stub).
  - Deeply grounded: real file src/DeFiLending.sol, real concepts (depositIndex, UUPS, ERC1967, liquidation, forge), with LINE-NUMBER citations ("Events (lines 39–43)").
  - Structured: High-Level Overview / Component Map / Core Contract (Inheritance, State Layout, Events, Function Reference, Key Formulas).
  - The scan flagged a REAL security finding: a committed npm auth token in .npmrc — plus design risks (exact-amount repayment, no liquidation incentive, owner-only manual liquidation).
- Verified: doc_needs_generation=False; abstract injected in the documentation section + retrieval pointer; get_repo_documentation returns the full doc; UI /briefing shows all 9 sections incl. documentation.
- Left the doc in place (accurate real content, unlike the iter16 stub). NO bugs. Stack healthy.
- SECURITY NOTE for the user: the deep-doc scan surfaced a committed npm auth token in defi-lending-contract/.npmrc — worth rotating/removing.

## Iteration 18 (FULL golden-path lifecycle on a polyglot C++/gRPC/React repo)
- cpp-grpc-react-boilerplate (fresh): full real-user lifecycle in one pass.
- init ✓ — .mcp.json has type:sse (iter14 fix confirmed on a fresh init).
- 7-section autogen ✓ (~180s) — grounded, identified the 3-tier "React app talking to a C++ gRPC service" architecture. 8 sections.
- real deep-doc ✓ (~190s) — 18,424 chars, grounded across tiers (mentions gRPC, React, .proto). Abstract in documentation section.
- ALL 9 sections present; needs_generation=False AND doc_needs_generation=False; verified in CLI folder-summary AND UI /briefing (9 sections).
- Proves the whole lifecycle works E2E on a fresh polyglot repo after both bug fixes (iter6 key-scoping, iter14 type:sse). NO bugs. Stack healthy.

## Iteration 19 (ERROR-PATH / input-validation sweep — BUG FOUND + FIXED)
- Cheap non-LLM robustness sweep of REST + MCP error branches (varied away from happy paths, all proven).
- REST folder-summary probes: bogus valid-UUID→404 ✓, missing folder_id→422 ✓, no auth→401 ✓, garbage key→401 ✓, BUT malformed non-UUID folder_id→500 ✗ (BUG).
- Root cause: non-UUID folder_id flowed into the folders ownership query on a uuid column → Postgres 22P02 'invalid input syntax for type uuid' → uncaught → 500.
- Fix (commit): added _is_uuid guard in folder_summary → returns 404 for any non-UUID (consistent with well-formed-but-nonexistent). Verified: not-a-uuid/garbage/SQL-ish strings → 404; real folder still 200. Added regression test; 5/5 folder-summary tests pass. Backend restarted.
- Checked other endpoints: UI /api/folders/{id}/briefing already 404s on non-UUID (not affected); session-capture does its scope check in Python (safe). Bug was isolated to CLI folder-summary.
- Stack healthy.

## Iteration 20 (MCP tool error branches + capture rate-limit — robustness)
- Continued the error-probing angle (iter19 found a bug there).
- MCP tool bad-input probes (all return graceful "Error:" strings, no exceptions/session drops):
  - update_folder_briefing_section bad section → "Error: Unknown section ... Valid: [...]"
  - save_repo_documentation empty content → "Error: content is empty."
  - get_folder_briefing / update / get_repo_documentation with a non-existent folder → "Error: No folder named '...' in your scope."
  - replace_folder_briefing non-object → "Error: sections must be a JSON object ..."
  - replace_folder_briefing invalid JSON → "Error: sections argument must be valid JSON: ..."
- Capture rate-limit ✓ — 6 captures/window succeed, then HTTP 429 with Retry-After:597. Graceful: the CLI watermark only advances on a successful SAVE, so a rate-limited capture is not lost (next one captures the accumulated delta).
- NO bugs found. All error branches robust. Stack healthy.

## Iteration 21 (SECURITY: api-key scope enforcement on folder-summary — BUG FOUND + FIXED)
- Tested scope isolation of repo-scoped keys (iter6). Found: GET /api/cli/folder-summary checked only OWNERSHIP (folders.user_id), NOT scope containment — so repo A's key returned HTTP 200 with repo B's full briefing (sibling repos readable). Inconsistent with session-capture + MCP tools (which enforce scope); a leftover from the pre-iter6 root-scoped era.
- Impact: a leaked repo api key (lives in .mcp.json) could read ALL the user's briefings, not just its repo — defeating repo-scoping isolation.
- Fix (commit): folder_summary now enforces folder_id ∈ key's scope subtree (via _descendant_folder_ids, same as capture), returning 403 otherwise. Fast path: reading the scope folder itself skips the walk; a root-scoped key still reaches its whole subtree.
- Verified: own→200; repo-scoped key→sibling repo→403 (was 200); root-scoped key→child repo→200 (backward-compatible); root→root→200. 7 backend tests pass.
- Stack healthy.

## Iteration 22 (AUTHZ AUDIT — confirm iter21 was the only scope gap)
- After the iter21 folder-summary fix, audited every other api-key-authed folder-access path for the same cross-scope bug class (passing a SIBLING repo's UUID):
  - get_folder_briefing(folder=<sibling UUID>) → "Error: Folder '...' is not inside your scope." ✓
  - save_repo_documentation(folder=<sibling UUID>) → blocked ✓
  - update_folder_briefing_section(folder=<sibling UUID>) → blocked ✓
    (all via resolve_focus_folder, which requires UUID ∈ scope subtree)
  - session-capture out-of-scope folder_id → HTTP 403 ✓
  - revoke_api_key with bogus/non-owned key id → HTTP 404 (user_id filter) ✓
- CONCLUSION: iter21 (folder-summary) was the ONLY endpoint missing scope enforcement; the MCP tools, capture, and key revocation were always correct. Isolation now complete + consistent across the api-key surface.
- NO new bugs. No code change (audit). Stack healthy.

## Iteration 23 (CONCURRENT-INIT race — BUG FOUND + FIXED)
- Ran 3 concurrent `kioku init --yes` on the same fresh repo (socket-flow, remote name 'simple-websocket').
- BUG: one init aborted with "✗ 409 Conflict: A folder named 'simple-websocket' already exists at this parent" + exit 1. All 3 pass listChildren (no folder yet), then race on createFolder; the backend's unique-name constraint 409s the losers.
- Post-race state WAS consistent (backend prevented a duplicate folder; final key valid, folder-summary 200, 1 folder, 1 key) — so no corruption, but a scripted/double init fails ugly.
- Fix (commit): createOrAttach() wraps the repo-binding createFolder calls — on a 409 it re-lists and attaches to the winner's folder instead of aborting. CLI rebuilt; 11/11 tests pass.
- Verified with fix: 3 concurrent inits on a fresh repo (discord-bot) ALL succeed (was 1 abort); final state 1 folder, 1 valid key, .mcp.json type:sse, folder-summary 200.
- Residual (not fixed, didn't manifest): the backend key-mint delete-then-insert for the same (user,scope) is theoretically racy (could 23505 on perfect interleave) but did not error under 3x concurrency and resolves to a single valid key. Deeper backend change; deferred.
- Stack healthy.

## Iteration 24 (mint-race residual from iter23 — probed directly)
- Fired 10 concurrent POST /api/api-keys for the SAME (user, scope): ALL 200, final state exactly 1 key. The delete-then-insert did NOT produce a 23505/500.
- WHY it's safe: single uvicorn worker + SYNCHRONOUS Supabase client → no `await` between create_api_key's delete and insert, so each request's delete+insert is effectively atomic vs. other requests. The event loop can't interleave mid-mint.
- DEPLOYMENT NOTE (for the future other-host deploy): under multiple workers/processes (e.g. gunicorn -w N) this atomicity is lost — concurrent same-scope mints across workers could 23505 → 500. Harden then (catch 23505 + retry, or an upsert/transaction). Not fixed now: doesn't manifest single-worker, final state always consistent.
- Cleanup: the 10 test mints revoked restful-rust's .mcp.json key (401); re-init restored it (200).
- NO bug. No code change. Stack healthy.

## Iteration 25 (doctor diagnostic accuracy — BUG FOUND + FIXED)
- Tested doctor's failure DETECTION (only ever seen all-green before).
- Missing-file detection ✓ — removing .mcp.json → "✗ .mcp.json"; removing CLAUDE.md → "✗ CLAUDE.md". Works.
- BUG (diagnostic gap): revoked the repo's .mcp.json api key → doctor STILL said "All checks passed". None of its checks validate the key: "MCP reachable" pings an UNAUTHENTICATED health endpoint, ".mcp.json" only checks file existence, "Login token" uses the SESSION token (not the .mcp.json key). So doctor gives a false all-clear while Claude Code's hook + all MCP tools would 401 silently.
- Fix (commit): added an "API key valid" check that calls folder-summary with the actual .mcp.json key; a 401/403 → "✗ API key valid — rejected (HTTP 401)" + "run: kioku init" and fails the summary. Only a confirmed rejection fails (missing key/state doesn't double-report). CLI rebuilt; 11/11 tests pass.
- Verified: valid→✓ + all pass; revoked→✗ rejected + "Some checks failed"; restored→✓.
- Stack healthy.

## Iteration 26 (hook robustness under backend-down — no bug; small UX polish)
- Critical untested property: the SessionStart + Stop hooks run every Claude Code session — do they degrade gracefully when the backend is unreachable? Simulated by pointing a test repo's .mcp.json url at a dead port (:9999).
- session-start ✓ — exits 0 in ~0.12s (no hang, no block). Was printing terse "kioku: fetch failed".
- capture (Stop hook) ✓ — exits 0 in ~0.59s, silent (never fails a hook, as designed).
- So the important robustness holds (fast, exit 0, non-blocking). NO bug.
- Small UX polish (commit): session-start now prints "kioku: backend unreachable — skipping briefing this session (your session is unaffected)." for the common connection-refused/DNS/timeout case instead of "fetch failed" — since it appears in the user's session every start when self-hosting and the backend is briefly down. Still exits 0. 11/11 tests pass.
- Stack healthy.

## Iteration 27 (file-mutation safety: CLAUDE.md / .gitignore content preservation)
- High-severity area (user-file corruption) — tested updateClaudeMd/updateGitignore against crafted user content.
- Append (existing CLAUDE.md w/ user rules) → user content preserved + our block added once ✓
- Update in place (re-run) → user content preserved, no duplicate block ✓
- Block SANDWICHED (user content BEFORE and AFTER our block) → both survive an update, order preserved (before<block<after), 1 block ✓
- .gitignore → user entries (node_modules, custom-user-entry.log) preserved, our entries added exactly once (idempotent) ✓
- NO bug. Marker-based before+SNIPPET+after logic is correct in all positions. No code change. Stack healthy.

## Iteration 28 (hook robustness to corrupt/malformed state files)
- The hooks read .mcp.json + kioku-state.json every session; tested malformed inputs:
  - A. truncated/corrupt .mcp.json → session-start & capture both exit 0 ✓
  - B. garbage kioku-state.json → both exit 0 ✓
  - C. empty .mcp.json → both exit 0 ✓
  - D. valid JSON but no 'kioku' server entry → both exit 0 ✓
- All degrade gracefully (JSON.parse try/catch guards). No crash, clean exit in every case. NO bug. Stack healthy.

## Iteration 29 (knowledge_base_search / search_memory — the RAG-search core, untested until now)
- knowledge_base_search callable via MCP; for a briefing-only repo (cpp) → "No relevant content found" (CORRECT: repo folders have no ingested docs; the deep-doc is on-demand via get_repo_documentation, not indexed into the search corpus).
- Against a folder WITH ingested documents (agentic-rag, 8d8847cf) → knowledge_base_search('ingestion pipeline') returned 5392 chars of GROUNDED content (real PR #16 doc). RAG retrieval path works end-to-end. ✓
- search_memory('preferences') → graceful "No memories matched." (that folder's test memories were deleted in iter8). ✓
- Confirms the search feature works when content exists and degrades gracefully when empty; the deep-doc/search separation is by design. NO bug. Test key cleaned up. Stack healthy.

## Iteration 30 (REGRESSION BATTERY — confirm all 6 loop fixes still hold)
- iter6  repo-scoped key reads own folder → 200 ✓
- iter14 fresh .mcp.json carries type:sse ✓
- iter19 malformed folder_id → 404 ✓
- iter21 cross-scope read blocked → 403 ✓
- iter23 concurrent-init createOrAttach present in build ✓
- iter25 doctor "API key valid" check present + passes on healthy repo ✓
- Test suites: CLI 11/11 pass, backend 105 passed. ZERO regressions. Stack healthy.

## Iteration 31 (multi-worker mint race: REPRODUCED real bug; attempted fix reverted)
- Reproduced the iter24 residual under a temp 4-worker uvicorn (:8010, same DB): 15 concurrent same-scope mints → 4×200, 11×500 (23505 unique-constraint violations). CONFIRMED real bug for the planned multi-worker deploy.
- Attempted fix: replace delete-then-insert with an atomic upsert (INSERT ... ON CONFLICT DO UPDATE). Single upsert works, BUT under high same-key concurrency the 4 workers HUNG (ON CONFLICT DO UPDATE waits on the conflicting row's lock; combined with the sync/blocking Supabase client it tied up the whole worker pool → :8010 unresponsive). That's WORSE than a fast 500.
- REVERTED the change (won't ship an unverified fix that regressed in my own test). Codebase back to known-good delete-then-insert. Cleaned test keys; restored restful-rust (folder-summary 200). Main :8000 stack never touched, healthy throughout.
- CORRECTED recommendation for deploy time: use retry-on-23505 (delete+insert, catch the 23505, retry — fail-fast, never waits on a lock), NOT upsert (which hangs here). Or a pg advisory lock keyed on (user,scope). Must be tested under real multi-worker + connection pooling before shipping.
- NET: valuable — race is real (reproduced) and the "obvious" upsert fix is a trap. No code shipped. Stack healthy.

## Iteration 32 (multi-worker mint hardening — attempted retry fix, UNVERIFIED, reverted; stopping)
- Implemented retry-on-23505 in create_api_key (delete+insert, catch 23505, retry with backoff; fail-fast, no lock wait).
- Verification under temp 4-worker :8010 HUNG (2-min timeout) at 15 AND at 3 concurrent. BUT this is likely CONFOUNDED: the prior iteration's 4-worker instance was killed with `kill -9`, which doesn't cleanly close DB connections — a hard-killed transaction can hold row locks on the (user,scope) rows until Postgres times it out, blocking all subsequent delete/insert there. So the "retry hangs at 3" result is unreliable (may be a leftover lock, not the retry).
- DECISION: reverted the retry change (unverified — did not pass a clean test). Codebase back to known-good delete-then-insert. Main :8000 unaffected (restful-rust re-init mint → 200, so no dangling lock on prod). Clean tree except ledger.
- STOPPING multi-worker experiments in the loop: each repro needs a temp 4-worker instance, and killing it (-9) risks leaving dangling locks that pollute the next test — not safe/productive to iterate on here.
- DEFINITIVE STATE for deploy time: the multi-worker mint race is REAL (reproduced cleanly in iter31: 11/15 → 500). The fix (retry-on-23505 or a pg advisory lock on (user,scope)) must be designed AND tested against the real deploy infra (proper async client / connection pooling / pgbouncer), not the dev single-sync-client setup. Do NOT use INSERT..ON CONFLICT (iter31: lock-wait hang).
- Stack healthy.

## Iteration 33 (back to disciplined basics — clean env check + fresh init+verify)
- Post-experiment cleanup verified: stack healthy, NO stray :8010 process, git tree clean (0 uncommitted), api_keys queryable (13 rows, no dangling lock from the -9 kills). Environment is clean after iter31-32.
- Clean init+verify on tweet-locator (fresh): detected haykadamyan/tweet-locator, wired folder+key+hooks; .mcp.json has type:sse; folder-summary needs_generation=True + 7 stable sections; doctor "✓ API key valid — authenticates OK" + "All checks passed."
- All this loop's fixes confirmed working together on a fresh repo (type:sse, repo-scoped key, doctor key-validation). NO bug. Stack healthy.

## Iteration 34 (full happy-path pipeline regression on a fresh JS repo)
- Completed the literal loop cycle on tweet-locator (Next.js + Express, JS): init → autogen (~80s) → grounded briefing → verify.
- overview grounded: "A Next.js + Express web app that searches geolocated tweets: pick a spot on a Google Map ..." ✓
- needs_generation=False, 8 sections in CLI folder-summary AND UI /briefing (9th=documentation not generated, expected).
- Confirms the whole init→autogen→briefing→folder-summary+UI pipeline still works end-to-end after all 33 prior iterations of changes. NO bug. Stack healthy.

## Iteration 35 (BUG FOUND + FIXED: CLAUDE.md documents wrong MCP tool param names)
- Testing save_memory MCP tool → validation error "content Field required". The injected CLAUDE.md (written by kioku init into every repo) documented tool calls with WRONG argument names:
  - save_memory(text, category=...)        → actual param is 'content'
  - query_documents_metadata(query)         → actual param is 'question'
  A Claude session following those instructions verbatim would get a validation error and the call fails.
- Audited all 8 tools in the snippet: the rest already matched (get_folder_briefing(folder), search_memory(query), knowledge_base_search(query), update_folder_briefing_section(section,content,pin), list_folders_in_scope(), get_folder_orientation()).
- Fix (commit): corrected save_memory→content and query_documents_metadata→question in cli/src/lib/claude.ts. CLI rebuilt; 11/11 tests pass. Verified save_memory(content=...) → {ok:true} saves fine.
- OPERATIONAL FINDING (flag to user): the Mem0 CLOUD QUOTA is EXHAUSTED — RateLimitError "quota_used 1000/1000, resets 2026-08-01". Mem0-backed features (capture saves, save_memory, memory search) will be limited until reset/upgrade.
- Graceful degradation CONFIRMED: session-capture returns HTTP 200 (not 500) even with Mem0 quota exhausted — the Stop hook won't break.
- Minor: one SM2-TEST-b7 memory saved during the test couldn't be deleted (Mem0 search is quota-blocked); it'll linger in the agentic-rag folder until quota resets. Low impact.
- Stack healthy.

## Iteration 36 (hands-on validate the iter35 CLAUDE.md param fix)
- Called query_documents_metadata(question='What documents exist?') hands-on → 1647 chars, real text-to-SQL over the documents table (SELECT DISTINCT ON (source_filename) ... WHERE user_id=... AND root_folder_id=...). Works with the CORRECTED 'question' param.
- Negative check: calling with the OLD wrong param query= → "Error executing tool ... 1 validation error" REJECTED. Confirms the iter35 mismatch was real (old CLAUDE.md doc would have failed) and the fix is correct.
- Note: query_documents_metadata works despite Mem0 quota exhaustion (it hits Postgres documents table, not Mem0).
- NO new bug — iter35 fix validated end-to-end. Stack healthy.

## Iteration 37 (FINDING flagged, not blindly fixed: pins don't survive regen)
- CLAUDE.md claims "Pinned sections survive auto-regen." Tested empirically (image-to-ascii, snapshot/restore): pinned a section (update_folder_briefing_section pin=True), then simulated a regen via replace_folder_briefing → the pinned content was OVERWRITTEN (survived=False, overwritten=True). Restored cleanly.
- Root cause: replace_folder_briefing's merge does `current[key] = new_section(content, ...)` for EVERY provided section with NO check of the existing section's pin status. The background autogen calls replace_folder_briefing with all 7 sections, so it overwrites any user-pinned section.
- WHY NOT auto-fixed here (design decision for the user): the correct fix is 2-part and has migration implications, so it's not a safe blind change:
  1. replace_folder_briefing must SKIP sections currently status="pinned" (preserve user pins).
  2. BUT the autogen currently writes with pin_all=True (default), so it pins everything → if we skip pinned, a re-autogen would skip ALL sections and never refresh. So the autogen's generateInstruction must call replace_folder_briefing with pin_all=FALSE (autogen content = "auto", regenerable; only explicit user pins are protected).
  3. MIGRATION: existing repos already have autogen sections marked status="pinned" (from the current default) — after the fix they'd be frozen (never regen). Needs a one-time downgrade of autogen-authored pins to "auto", or the fix only helps new repos.
- RECOMMENDATION to user: decide whether to (a) implement the 2-part fix + migration to make pins truly protective, or (b) soften the CLAUDE.md claim. I did NOT change code (touches designed pin semantics + migration). NO code change. Stack healthy.

## Iteration 38 (doc-accuracy: stale "8-section" → 9 across docstrings + CLAUDE.md + help)
- CLAUDE.md described get_folder_briefing() as an "8-section briefing" omitting the documentation section (SECTION_KEYS has 9). Fixed (commit).
- Found MORE stale "8-section" refs: 4 MCP tool docstrings in mcp_server.py (get_folder_briefing/orientation — these ARE the tool descriptions Claude reads), replace_folder_briefing's docstring, and the `kioku briefing` CLI help. Fixed all → 9-section; reworded replace_folder_briefing to note it writes the STABLE sections (activity live, documentation via save_repo_documentation).
- CLI rebuilt (11/11 tests pass), mcp_server.py syntax OK, MCP :8001 restarted to serve the corrected tool descriptions. Verified post-restart: tools list works + get_folder_briefing description now says "9-section".
- Doc/behavior now consistent. Stack healthy.

## Iteration 39 (doc-accuracy: stale removed-feature ref in a Claude-facing message)
- Audited CLAUDE.md + MCP tool docstrings for references to the REMOVED GitHub-sync subsystem.
- CLAUDE.md clean (my earlier grep hits were false positives — 'sync' in existsSync/writeFileSync). Cross-check: every tool mentioned in CLAUDE.md has a real MCP def.
- BUG: get_folder_briefing returned "Briefings are only available for GitHub-synced folders" for non-repo folders (mcp_server.py:800) — GitHub sync was removed; repo folders are now made via `kioku init` on a clone. Fixed the Claude-facing message → "for repo folders (run kioku init in a cloned repo)". MCP restarted to serve it.
- Left alone (intentional): the github_connected metadata field in get_folder_orientation — unused by the frontend, and a code comment documents it as a deliberate repurpose to mean kind=="repo" (backward-compat). Not misleading any consumer.
- Stack healthy.

## Iteration 40 (comprehensive MCP tool-description audit)
- Dumped all 20 MCP tool descriptions (what Claude reads) + regex-scanned for stale content (github-sync, section counts, root-scoped, etc.).
- "root-scoped" refs (list_folders_in_scope, get_folder_briefing, get_folder_orientation): NOT stale — they accurately describe root-scoped-key behavior, which still works (repo-scoping is just the new default from iter6). Left as-is.
- BUG (missed in iter38): replace_folder_briefing docstring said "one of the 8 section names" (I'd fixed '8-section' but not '8 section'). Fixed → reference get_folder_briefing_schema for the authoritative list + shapes (avoids a brittle count; valid set is 9, agent authors the stable ones). MCP restarted.
- Final sweep: no remaining numeric section counts in docstrings. Doc-accuracy seam fully swept over iters 35/38/39/40.
- Stack healthy.

## Iteration 41 (notes CRUD — previously-untested feature)
- Exercised save_note / list_notes / delete_note via MCP (never tested before).
- save_note requires title+content (clear validation — my first call missed title, got a proper "title Field required" error, not a crash).
- Round-trip ✓: save_note(title,content) → "Note saved (id ...)"; list_notes shows it (formatted: **title** (id, date) content); delete_note(note_id) → "Note deleted."; list_notes after → gone.
- Notes are a separate store (not Mem0), so unaffected by the Mem0 quota. Test note cleaned up. NO bug. Stack healthy.

## Iteration 42 (context tools — previously-untested feature)
- Exercised set_context / get_context / list_context / clear_context via MCP (never tested).
- Round-trip ✓: set_context(key,value) → "Context set"; get_context(key) → value round-trips; list_context → shows "**key**: value (expires: 2026-07-24)" — note context has a 7-day TTL; clear_context(key) → "Context cleared"; get after → "No context found."
- Params clear (set: key+value required; get/clear: key). Test context cleared. NO bug. Stack healthy.
- Untested tools now down to just evaluate_retrieval.

## Iteration 43 (evaluate_retrieval — LAST untested tool, was FULLY BROKEN: 2 bugs found + fixed)
- Exercised evaluate_retrieval (RAGAS eval) hands-on — the final untested MCP tool. It errored on EVERY valid call.
- BUG 1: evaluate_rag_pipeline is `async def` but evaluate_retrieval (sync tool) called it WITHOUT await → 'coroutine object is not subscriptable' when indexing result["aggregate"]. Fix: made evaluate_retrieval `async def` + `await` (FastMCP supports async tools; knowledge_base_search already is one).
- BUG 2 (revealed after fixing 1): RAGAS returns None for an uncomputable metric (e.g. empty context); the '{score:.3f}' formatting then raised 'unsupported format string passed to NoneType'. Fix: _fmt() helper prints 'N/A' for non-numeric scores (both the aggregate + per-question loops).
- Verified end-to-end: tool now retrieves, generates an answer ("...two distinct ingestion pipelines..."), reports scores (faithfulness=N/A, answer_relevancy=0.611, context_precision=0.804). MCP restarted; stack healthy. Test key cleaned up.
- MILESTONE: all 20 MCP tools now hands-on validated. This one being fully broken shows the "actually call every tool" approach pays off.

## Iteration 44 (audit the iter43 bug CLASS: sync-calls-async-without-await)
- After finding evaluate_retrieval's missing-await bug, systematically audited the whole backend for the same class: every `async def` in services/ cross-checked against its call sites in mcp_server.py and routes/.
- mcp_server.py: only 2 async service fns are called (evaluate_rag_pipeline, fanout_search) — BOTH awaited (evaluate was the iter43 fix). Clean.
- routes/: no async service fn called without await. Clean.
- CONCLUSION: the iter43 async/await bug was ISOLATED — no other broken tools/endpoints of that class. Fix was complete.
- NO new bug. No code change. Stack healthy.

## Iteration 45 (NOTION SYNC — the branch's namesake feature, never tested before; BUG FOUND + FIXED)
- Discovered the whole Notion-sync subsystem (routes/notion.py, services/notion_sync/*, 7 test files, NotionIntegrationSection.tsx) — the feat/notion-sync branch's core feature, untested by the loop until now.
- Notion unit tests: 22 passed. User HAS 1 Notion config connected (GET /api/notion/configs → 200, 1 config).
- Error-path testing of /api/notion endpoints found a BUG (same class as iter19): a MALFORMED (non-UUID) config_id → HTTP 500 (Postgres 22P02 on the uuid column) on /configs/{id}/sync, /reconcile, and DELETE /configs/{id}. Valid-but-nonexistent UUIDs correctly 404.
- Fix (commit): added _is_uuid guard in notion.py, applied to _enqueue_sync (covers sync+reconcile) and disconnect → 404 for malformed ids. Backend restarted; 12 tests pass.
- Verified: malformed id → 404 on all 3 endpoints; non-existent valid UUID → 404; GET /configs still 200; no-auth → 401.
- NOT tested (needs live Notion OAuth beyond the connected config / would trigger real syncs): actual sync/reconcile execution, page ingestion, block→markdown conversion (covered by unit tests though).
- Stack healthy.

## Iteration 46 (SYSTEMATIC AUDIT + fix: malformed-id → 500 was WIDESPREAD)
- Followed up the iter19+iter45 pattern with a repo-wide sweep: enumerated every id-path-param endpoint and hit each with a malformed id (not-a-uuid).
- Found the bug class in 10+ endpoints across 6 routers → HTTP 500: api-keys revoke; conversations get/rename/delete; context delete; notes delete; ingestion-jobs get; mem0 disconnect/deduplicate/verify/list-memories/delete-memory. (folders/briefing already 404/422.)
- Fix (commit): new shared routes/_validation.py (is_uuid + require_uuid→404), guard added to all affected endpoints. Backend restarted; full suite 105 passed.
- Verified: re-sweep — ALL previously-500 endpoints now return 404 on a malformed id; valid endpoints (GET /conversations, /notes, /mem0/configs) still 200.
- Follow-up (optional DRY): iter19 (cli.py) + iter45 (notion.py) have local _is_uuid copies that could migrate to routes/_validation.require_uuid.
- Stack healthy.

## Iteration 47 (extend the malformed-id sweep to QUERY params + body)
- iter46 did path params; swept QUERY-param + POST-body ids next.
- QUERY-param root_folder_id → 500 (bug) on: GET /notes, GET /context, DELETE /context/clear, GET /mem0/memories/rules, GET /mem0/memories/recent.
- POST-body ids (POST /notes, POST /notion/configs with malformed root_folder_id) → 400 (already graceful, no fix needed).
- Fix (commit): require_uuid guard — only-when-provided for the optional list filters (notes/context), and via the shared mem0 _validate_folder + _load_client helpers (covers rules/recent + future folder-validating endpoints in one place).
- Verified: all query-param endpoints now 404; no-filter list_notes/list_context still 200; backend suite 105 passed.
- The malformed-id → 500 class (path + query) is now comprehensively closed across the API.
- Stack healthy.

## Iteration 48 (numeric param bounds — new validation class; BUG FOUND + FIXED)
- Varied from the id class to NUMERIC bounds: tested endpoints with limit/days/threshold params using negative/zero/huge values.
- retrieval-log (limit=-1/0/huge, since_days=-5) → all 200 (Supabase tolerates them). limit=abc → 422 (type validation). Clean.
- BUG: GET /folders/{id}/summary/history?limit=-1 → 500. get_summary_history does .limit(limit) → Postgres LIMIT -1 → raises → uncaught 500. (limit=0/huge were 200; only negative broke.)
- Fix (commit): bound the param with Query(ge=1, le=100) → 422 for out-of-range. Frontend passes limit=10 (default, no explicit >100 call sites) → no client impact.
- Verified: limit=-1/0/999999 → 422; limit=5 + default → 200; backend suite 105 passed.
- Follow-up noted: mem0 list endpoints have unbounded limit params too, but couldn't be cleanly tested (Mem0 quota exhausted); some go to Mem0's API not Postgres. Worth bounding when quota allows testing. Also: folders.py has its own _require_uuid (3rd local copy — DRY candidate w/ routes/_validation).
- Stack healthy.

## Iteration 49 (DRY concern resolved SAFELY by verification, not risky refactor)
- 3 local uuid-guard copies exist: cli.py _is_uuid (uuid.UUID), notion.py _is_uuid (uuid.UUID), folders.py _require_uuid (REGEX _UUID_RE), plus the shared routes/_validation (uuid.UUID).
- The real risk of duplicated guards is DIVERGENCE. Verified behavioral consistency: tested the regex vs uuid.UUID implementations across 10 edge cases (malformed/empty/SQL-ish/no-hyphens/non-hex/trailing/valid) → 0 mismatches. The copies agree exactly.
- DECISION: did NOT consolidate. It would be aesthetic-only (copies work + are consistent) and carries subtle-regression risk (regex vs uuid.UUID edge cases) not worth taking in an unattended loop (iter31-32 lesson). Left as a documented human-refactor task: replace the 3 local copies with routes/_validation.{is_uuid,require_uuid}.
- NO code change. NO bug. Stack healthy.

## Iteration 50 (untested route file: documents.py — malformed folder_id class extends here)
- Tested documents.py (upload/list/content/download/move/delete + ingestion-status) — untested route file until now. Uses {filename} path params (DB text match, NOT filesystem paths → no traversal risk).
- BUG (iter47 class, not swept in documents.py): GET /documents?folder_id=<non-uuid> and GET /documents/{filename}/content?folder_id=<non-uuid> → 500 (.eq folder_id on uuid col). Others were graceful: download 404, move 422, delete 200, ingestion-status has no id param.
- Fix (commit): require_uuid guard (only-when-provided) on both list_documents + get_document_content.
- Verified: both → 404 on malformed folder_id; list + valid-folder filter → 200; backend suite 105 passed.
- Stack healthy. NOTE: upload/ingestion (POST /upload) not exercised (needs multipart file + would trigger real embedding/ingestion); its logic is partially covered by chunker/embeddings unit tests.

## Iteration 51 (last untested route files: chat.py + drop.py; BUG in chat)
- chat.py POST /chat: malformed conversation_id → the id reached the uuid column inside stream_rag_response (rag.py insert into messages) → 22P02 → CRASHED the SSE generator. Client got a silent empty stream (HTTP 200 with no body); server logged a traceback. Malformed-uuid class in the streaming path.
- Fix (commit): require_uuid guard in the chat endpoint BEFORE the StreamingResponse → clean 404. Verified: malformed conv_id → 404; no 22P02 in log; suite 105 passed.
- drop.py POST /drop (api-key auth, multipart upload): validation works — bad bearer → auth error, unsupported extension → 400. (Real ingestion not triggered.) No bug.
- NOTED follow-up (not fixed): a valid-but-NONEXISTENT conversation_id would also crash the generator (FK violation on messages.conversation_id insert) — separate from the malformed case; needs an ownership check before streaming. Lower priority (normal clients create the conversation first).
- All route files now swept for the malformed-id class. Stack healthy.

## Iteration 52 (core-flow regression after 51 iters of backend changes)
- Returned to the literal loop task (full init→autogen→verify) as a regression check that the extensive backend input-validation work + many restarts didn't break the core pipeline.
- finance-advisor-ai (Go + SQL, WhatsApp finance assistant): init (type:sse ✓, activity showed ahead/behind tracking "ahead 0, behind 4") → autogen (~70s) → grounded 8-section briefing ("WhatsApp-based personal finance assistant ... an LLM turns free-text into expenses").
- needs_generation=False, 8 sections in CLI folder-summary AND UI /briefing.
- Core pipeline healthy end-to-end after 51 iterations of changes. NO bug. Stack healthy.
