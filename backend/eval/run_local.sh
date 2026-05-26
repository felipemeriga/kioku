#!/usr/bin/env bash
# Run the eval harness against a local Supabase stack.
#
# Idempotent: safe to run repeatedly. Each invocation truncates the documents
# table for EVAL_USER_ID so the ingestion step re-runs without dedup skips.
#
# Usage:
#     ./backend/eval/run_local.sh              # IR-only full eval (~3-5 min)
#     ./backend/eval/run_local.sh --quick      # IR-only, 9-question subset (~1 min)
#     ./backend/eval/run_local.sh --ragas      # add RAGAS metrics (slow, hours)
#     ./backend/eval/run_local.sh --gate       # also compare to baseline.json
#     ./backend/eval/run_local.sh --capture    # capture this run as new baseline

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EVAL_USER_ID="00000000-0000-0000-0000-000000000001"

GATE=""
QUICK=""
RAGAS=""
CAPTURE=""
for arg in "$@"; do
    case "$arg" in
        --gate)    GATE="--gate" ;;
        --quick)   QUICK="--quick" ;;
        --ragas)   RAGAS="--ragas" ;;
        --capture) CAPTURE=1 ;;
        *)         echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

cd "$ROOT"

# 1. Make sure local supabase is up
if ! supabase status >/dev/null 2>&1; then
    echo "[eval] starting local supabase..."
    supabase start
fi

# 2. Pull connection details from the running stack
eval "$(supabase status --output env | grep -E '^(API_URL|SERVICE_ROLE_KEY|DB_URL)=')"
DB_URL="${DB_URL//\"/}"
SUPABASE_URL="${API_URL//\"/}"
SUPABASE_SERVICE_KEY="${SERVICE_ROLE_KEY//\"/}"

# 3. Apply schema (idempotent: CREATE TABLE IF NOT EXISTS / CREATE OR REPLACE)
echo "[eval] applying schema + local setup..."
psql "$DB_URL" -f backend/db/schema.sql >/dev/null
psql "$DB_URL" -f backend/db/local_setup.sql >/dev/null

# 4. Reload PostgREST schema cache (so newly-added columns are seen by the HTTP client)
psql "$DB_URL" -c "NOTIFY pgrst, 'reload schema';" >/dev/null

# 5. Clear any prior eval ingestion so dedup doesn't skip re-ingest
psql "$DB_URL" -c "DELETE FROM public.documents WHERE user_id = '$EVAL_USER_ID';" >/dev/null

# 6. Run the eval
export SUPABASE_URL SUPABASE_SERVICE_KEY
export LANGCHAIN_TRACING_V2="${LANGCHAIN_TRACING_V2:-false}"
export LANGSMITH_TRACING="${LANGSMITH_TRACING:-false}"
cd backend
uv run python -m eval.runner $QUICK $RAGAS $GATE

# 7. Optionally capture this run as the new baseline
if [[ -n "$CAPTURE" ]]; then
    echo
    echo "[eval] capturing this run as new baseline..."
    uv run python -m eval.update_baseline
fi
