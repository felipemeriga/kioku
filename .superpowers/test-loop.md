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
