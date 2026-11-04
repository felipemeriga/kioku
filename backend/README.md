# Kioku backend

FastAPI product API, scoped MCP service, and arq worker. See
[local development](../docs/development.md) for setup and commands,
[architecture](../docs/architecture.md) for retrieval/execution, and
[operations](../docs/operations.md) for deployment.

## Source map

| Path | Responsibility |
| --- | --- |
| `main.py`, `auth.py` | Lifecycle, router registration, product authentication |
| `routes/` | REST contracts and ownership/scope checks |
| `mcp_server.py` | Scoped MCP tools and SSE server |
| `services/search.py`, `rerank.py` | Candidate retrieval, ranking, recency, neighbors |
| `services/rag.py`, `tools.py` | API-backed agent loop and tool dispatch |
| `services/ai/` | Execution registry, Tsukai client, scopes, native bridge/consumption |
| `services/queue/` | arq jobs and worker settings |
| `services/notion_sync/` | Notion ingestion orchestration |
| `db/` | Supabase client, schema snapshot, local-only setup |
| `tests/` | Unit/integration fixtures and contracts |
| `eval/` | Retrieval quality harness and synthetic benchmark corpora |

The running app's `/docs` and `/openapi.json` are the REST contract index.
The schema snapshot is not a replacement for checking later migrations.
Do not run local seed/RLS shortcuts on production.

The backend/worker image includes ingestion dependencies. The MCP image excludes
the ingestion group and delegates queued parsing work to the worker. See the two
Dockerfiles before changing build dependencies.

[Eval guide](eval/README.md) · [API and MCP guide](../docs/integrations.md) ·
[documentation index](../docs/README.md)
