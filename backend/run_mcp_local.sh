#!/usr/bin/env bash
# Run the MCP server against the local Supabase stack on port 8001.
#
# Prereqs: same as backend/run_local.sh (supabase running, backend/.env.local
# filled in, schema applied). The MCP server reads from the same env file and
# the same database as the main backend — once you've set up local dev, this
# just works.
#
# Authenticating MCP clients:
#   The server validates Bearer tokens against the `api_keys` table. Create
#   a key by signing into the frontend (http://localhost:5173) and visiting
#   the Settings page, OR insert a row directly into local Supabase:
#
#     INSERT INTO public.api_keys (user_id, key_hash, scope_folder_id)
#     VALUES ('<your-user-id>', encode(sha256('mykey'::bytea), 'hex'), NULL);
#
#   Then point your MCP client at: http://localhost:8001/sse with header
#   `Authorization: Bearer mykey`.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/backend"

if [[ ! -f .env.local ]]; then
    echo "[run_mcp_local] backend/.env.local missing. Copy from backend/.env.local.example." >&2
    exit 1
fi

if ! supabase status >/dev/null 2>&1; then
    echo "[run_mcp_local] local Supabase isn't running. Start it with: supabase start" >&2
    exit 1
fi

exec uv run --env-file .env.local python -m mcp_server
