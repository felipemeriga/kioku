# Local development and validation

## Requirements

Use Docker, the Supabase CLI, `psql`, uv, and Node.js 22 (matching CI). The backend
supports Python 3.10+; Tsukai requires Python 3.12+. Frontend and CLI dependencies
are locked separately. Document parsing installs the backend ingestion dependency
group, including CPU vision packages.

## Database and configuration

From the repository root:

```bash
supabase start
supabase status --output env
cp backend/.env.local.example backend/.env.local
cp frontend/.env.local.example frontend/.env.local
```

Fill both local environment files from the local stack and add the real provider
keys needed for the paths you intend to exercise. Never copy production database
credentials into local setup. The backend example documents the Supabase, Anthropic,
Voyage, and optional Tavily/OpenAI values.

The checked-in backend launcher documents a schema-snapshot bootstrap:

```bash
psql postgresql://postgres:postgres@127.0.0.1:54322/postgres -c 'CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;'
psql postgresql://postgres:postgres@127.0.0.1:54322/postgres -f backend/db/schema.sql
psql postgresql://postgres:postgres@127.0.0.1:54322/postgres -f backend/db/local_setup.sql
```

`local_setup.sql` is development-only. The snapshot and incremental migrations
serve different workflows: inspect the initialized database's migration state
before applying feature migrations. Newer Tsukai features require their ordered
migrations under `supabase/migrations`; the snapshot alone is not a promise that
all later feature tables exist. Do not replay the entire migration history on top
of a snapshot blindly. The eval harness uses its own disposable snapshot setup.

## Start services

```bash
docker compose -f docker-compose.dev.yml up -d
cd backend
uv sync --frozen
```

Run each process in a separate terminal from the repository root:

```bash
./backend/run_local.sh
```

```bash
./backend/run_mcp_local.sh
```

```bash
cd backend
uv run --env-file .env.local arq services.queue.settings.WorkerSettings
```

```bash
cd frontend
npm ci
npm run dev
```

The backend listens on 8000, MCP on 8001, and Vite on 5173. Vite proxies `/api`
to the backend. Redis defaults to `redis://localhost:6379/0`; set `REDIS_URL` in
the backend local environment if needed. Sign in through the frontend to create
a local user. Create a scoped API key before connecting an MCP client.

For a local CLI session, explicitly override the hosted default:

```bash
export KIOKU_API_BASE=http://localhost:8000
export KIOKU_MCP_URL=http://localhost:8001/sse
kioku login
```

Tsukai is optional for API-backed development. Its runtime, isolated database,
credentials, migrations, and enablement requirements are described in
[Tsukai](../tsukai/README.md) and [operations](operations.md).

## Checks

Run the checks appropriate to the changed surface; these commands mirror the
checked-in checks workflow rather than requiring paid end-to-end calls.

| Surface | Commands from repository root |
| --- | --- |
| Backend and Mihari lint | `cd backend && uv sync --frozen && uv run ruff check . ../mihari && uv run ruff format --check . ../mihari` |
| Backend unit tests | `cd backend && uv run pytest tests/ -v` (Redis required by relevant tests) |
| Frontend | `cd frontend && npm ci && npx eslint . && npx tsc --noEmit && npm run test:run && npm run build` |
| CLI | `cd cli && npm ci && npm test` |
| Tsukai | `uv sync --project tsukai --frozen` then `uv run --project tsukai ruff check tsukai`, `uv run --project tsukai ruff format --check tsukai`, and `uv run --project tsukai pytest tsukai/tests -v` |
| Release scripts | `python3 -m unittest discover -s scripts/release -p 'test_*.py' -v` |

Tsukai PostgreSQL tests require isolated admin/runtime test URLs and fixture roles;
see `.github/workflows/checks.yml`. SQLite-only results do not validate grants,
RLS, or PostgreSQL locking. Frontend CI supplies placeholder Supabase environment
values for unit tests.

[Retrieval evaluation](../backend/eval/README.md) may call external providers.
[Manual E2E suites](../tests/e2e/README.md) include host-specific scripts and are
not a portable clean-checkout acceptance command.

## Documentation changes

Update the canonical guide and affected entry-point links together. Keep plans,
research reports, and fixture corpora identifiable as such. Check relative links,
Markdown code fences, and `git diff --check`; do not run inference or deploy merely
to validate prose. Record source/PR evidence and review date in the change-status page.
