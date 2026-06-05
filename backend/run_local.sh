#!/usr/bin/env bash
# Run the backend against the local Supabase stack.
#
# First-time setup:
#   1. Install Supabase CLI: `brew install supabase/tap/supabase`
#   2. From the project root: `supabase start` (boots the full local stack)
#   3. Apply schema + local setup:
#        DB="postgresql://postgres:postgres@127.0.0.1:54322/postgres"
#        psql "$DB" -f backend/db/schema.sql
#        psql "$DB" -f backend/db/local_setup.sql
#   4. Copy backend/.env.local.example -> backend/.env.local and fill in
#      values from `supabase status --output env`.
#   5. Copy frontend/.env.local.example -> frontend/.env.local likewise.
#   6. Sign up a dev user via the frontend (http://localhost:5173). That
#      creates a row in local auth.users that the backend will validate
#      against (via the local JWKS, fetched at runtime — no hardcoded keys).
#
# Then on each run:
#   ./backend/run_local.sh
#
# main.py calls load_dotenv() with the default override=False, so env
# values from `uv run --env-file .env.local` take precedence over any
# values in .env. Local overrides prod cleanly.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

if [[ ! -f .env.local ]]; then
    echo "[run_local] backend/.env.local missing. Copy from backend/.env.local.example and fill in." >&2
    exit 1
fi

if ! supabase status >/dev/null 2>&1; then
    echo "[run_local] local Supabase isn't running. Start it with: supabase start (from project root)" >&2
    exit 1
fi

exec uv run --env-file .env.local uvicorn main:app --reload --port 8000
