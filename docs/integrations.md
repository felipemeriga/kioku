# APIs, MCP, and external integrations

## REST API

The backend registers routers in `backend/main.py`. A running development instance
exposes FastAPI's `/docs` and `/openapi.json`; use these for exact request/response
contracts rather than a manually copied endpoint list.

| Area | Source |
| --- | --- |
| Chat, model catalog, replay, cancellation | `backend/routes/chat.py` |
| Documents and ingestion | `backend/routes/documents.py` |
| Repository knowledge and learnings | `backend/routes/briefing.py`, `backend/routes/learnings.py` |
| Machine presence and inventory | `backend/routes/remotes.py` |
| External file drop | `backend/routes/drop.py` |
| Native execution internals | `backend/services/ai/`, `tsukai/protocol/` |

User-facing routes generally use Supabase JWTs. Scoped keys authorize MCP and
specific programmatic routes such as file drops. Machine credentials authorize
presence/inventory, not arbitrary knowledge access. Internal native routes require
service authentication and scoped capabilities. Check each route's dependencies;
there is no single authentication rule that applies to every non-health route.

## MCP

Run `./backend/run_mcp_local.sh` for local SSE on port 8001. Prefer `kioku init`
for agent configuration; it creates a repository binding and scoped API key.
Create a key in the UI for a manually configured client:

```json
{
  "mcpServers": {
    "kioku": {
      "type": "sse",
      "url": "http://localhost:8001/sse",
      "headers": { "Authorization": "Bearer YOUR_SCOPED_API_KEY" }
    }
  }
}
```

Store the real config outside version control. Client transport support varies;
the CLI handles Claude Code and Codex configuration separately.

The tool surface in `backend/mcp_server.py` includes briefing/orientation,
document retrieval and metadata, repository documentation, and code navigation.
Use `find_definition`, `find_references`, `outline`, `impact_of`, and `code_search`
when registered by the current server. `knowledge_base_search` can blend documents
and indexed code. Empty results may mean missing/stale indexing, not missing source.

Pin structured repository facts with `update_folder_briefing_section`; detailed
repository documentation is a separate stored artifact. See the live tool schemas
for required parameters and scope resolution.

## GitHub, Notion, and drops

Repository registration and credentials are managed through the app/backend.
Mihari polls the principal branch and refreshes indexed knowledge. Notion sync
fetches configured content into document ingestion. `/api/drop` supports scoped
external uploads. Their credentials, scheduling, and scope belong to the server;
never embed service-role keys in a browser or committed agent configuration.

[Architecture](architecture.md) describes retrieval; [operations](operations.md)
describes deployment; [CLI](../cli/README.md) describes local agent setup.
