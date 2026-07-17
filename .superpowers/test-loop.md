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
