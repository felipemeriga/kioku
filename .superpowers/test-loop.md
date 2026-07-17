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
