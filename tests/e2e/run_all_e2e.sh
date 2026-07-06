#!/usr/bin/env bash
# Master E2E orchestrator. Runs every suite in sequence, isolates failure per
# suite, reports a summary table at the end.
#
# Usage:
#   /tmp/run_all_e2e.sh                # run everything
#   /tmp/run_all_e2e.sh --only rest    # run only tests matching 'rest'
#   /tmp/run_all_e2e.sh --list         # show what would run
#
# All suites live in /tmp — reruns are safe.

set -u -o pipefail

BE=/Users/feliperamosdasilva/personal_projects/agentic-rag/backend
RESULTS_DIR=/tmp/e2e_results_$(date +%s)
mkdir -p "$RESULTS_DIR"

# In dependency order — CLI E2Es come after backend probes since they
# assume backend + MCP are up. Auth-rate-limit-sensitive suites run
# last so we don't stomp on Supabase's 50s OTP cooldown.
SUITES=(
  "REST sanity walk:/tmp/e2e_bug_hunt_rest.py"
  "Cross-user isolation:/tmp/e2e_deep_crossuser.py"
  "Deep bug hunt round 1:/tmp/e2e_deep_cascade_and_races.py"
  "Deep bug hunt round 2:/tmp/e2e_deep_bughunt2.py"
  "Chat + SSE:/tmp/e2e_bug_hunt_chat.py"
  "MCP + detail page:/tmp/e2e_mcp_and_detail_page.py"
  "Claude Code first session:/tmp/e2e_claude_code_first_session.py"
  "Dedup Mem0:/tmp/e2e_dedup.py"
  "Multi-type file viewer:/tmp/e2e_multi_type_viewer.py"
  "Focus folder:/tmp/e2e_focus_folder.py"
  "Persona: UX Playwright:/tmp/e2e_persona_ux.py"
  "Persona: Developer with Claude Code:/tmp/e2e_persona_dev.py"
  "Persona: Bug hunter:/tmp/e2e_persona_bughunt.py"
  "Dev workflow:/tmp/e2e_dev_workflow.py"
  "Briefing lifecycle:/tmp/e2e_briefing_lifecycle.py"
  "Recent features (cron scope + replace briefing):/tmp/e2e_recent_features.py"
  "Cron scope enumerator:/tmp/e2e_cron_scope.py"
  "CLI capture (Stop hook):/tmp/e2e_cli_capture.py"
  "CLI smoothness:/tmp/e2e_cli_smooth.py"
  "CLI GitHub auth ladder:/tmp/e2e_cli_github_auth.py"
  "CLI pro tier:/tmp/e2e_cli_pro.py"
  "CLI (full lifecycle):/tmp/e2e_cli.py"
)

MODE="run"
FILTER=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --list) MODE="list"; shift;;
    --only) FILTER="$2"; shift 2;;
    -h|--help)
      echo "Usage: $0 [--only <pattern>] [--list]"
      exit 0
      ;;
    *) echo "unknown flag: $1"; exit 1;;
  esac
done

if [[ "$MODE" == "list" ]]; then
  printf "%s\n" "${SUITES[@]}"
  exit 0
fi

# Preflight — services up?
if ! curl -sf http://localhost:8000/api/health >/dev/null 2>&1; then
  echo "✗ backend not reachable at :8000"
  exit 1
fi
if ! curl -sf http://localhost:8001/health >/dev/null 2>&1; then
  echo "⚠ MCP not reachable at :8001 — MCP suites will fail"
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  Running $(( ${#SUITES[@]} )) E2E suites"
echo "  Results → $RESULTS_DIR"
echo "════════════════════════════════════════════════════════════════"

PASSED=()
FAILED=()
SKIPPED=()

for entry in "${SUITES[@]}"; do
  # Split on LAST colon so 'Persona: UX Playwright:/tmp/...' works.
  NAME="${entry%:*}"
  SCRIPT="${entry##*:}"
  SAFE=$(echo "$NAME" | tr '/ ' '__' | tr -c 'A-Za-z0-9_-' '_')

  if [[ -n "$FILTER" && "$NAME" != *"$FILTER"* && "$SCRIPT" != *"$FILTER"* ]]; then
    continue
  fi

  if [[ ! -f "$SCRIPT" ]]; then
    echo ""
    echo "⊘  $NAME"
    echo "    skipped — script not found: $SCRIPT"
    SKIPPED+=("$NAME")
    continue
  fi

  echo ""
  echo "▶  $NAME"
  START=$(date +%s)
  cd "$BE"
  if uv run python "$SCRIPT" > "$RESULTS_DIR/$SAFE.log" 2>&1; then
    ELAPSED=$(( $(date +%s) - START ))
    # Parse the "N pass, M fail" summary line if present
    SUMMARY=$(grep -E "^[A-Z ]+: [0-9]+ pass, [0-9]+ fail$" "$RESULTS_DIR/$SAFE.log" | tail -1)
    if [[ -z "$SUMMARY" ]]; then
      SUMMARY=$(tail -1 "$RESULTS_DIR/$SAFE.log")
    fi
    # Suite is a "pass" only if 'fail: 0'
    FAILS=$(echo "$SUMMARY" | grep -oE '[0-9]+ fail' | grep -oE '[0-9]+' | head -1)
    if [[ -z "$FAILS" || "$FAILS" == "0" ]]; then
      echo "   ✓ $NAME  (${ELAPSED}s) — $SUMMARY"
      PASSED+=("$NAME")
    else
      echo "   ✗ $NAME  (${ELAPSED}s) — $SUMMARY"
      FAILED+=("$NAME:$SUMMARY")
    fi
  else
    ELAPSED=$(( $(date +%s) - START ))
    echo "   ✗ $NAME  (${ELAPSED}s) — exit non-zero"
    tail -6 "$RESULTS_DIR/$SAFE.log" | sed 's/^/       /'
    FAILED+=("$NAME:exit-non-zero")
  fi
done

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  SUMMARY: ${#PASSED[@]} passed, ${#FAILED[@]} failed, ${#SKIPPED[@]} skipped"
echo "════════════════════════════════════════════════════════════════"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo ""
  echo "Failed:"
  for f in "${FAILED[@]}"; do
    echo "  ✗ $f"
  done
  echo ""
  echo "Logs: $RESULTS_DIR"
fi

# Exit code reflects pass/fail
if [[ ${#FAILED[@]} -eq 0 ]]; then
  exit 0
else
  exit 1
fi
