# Kioku (記憶)

**Second brain for your repos.** A persistent memory system that pairs with Claude Code — captures preferences, findings, decisions, and architecture briefings per-repo, and streams them back at the start of every session via MCP.

Upload PDFs, DOCX, Markdown, or plain text; connect GitHub repos + Notion pages; wire Claude Code hooks with a single CLI command. Every session starts with your repo's briefing pre-loaded; every session ends with what you learned auto-captured to memory.

Built as a self-hosted, folder-scoped second brain. Unlike per-project agents, Kioku unifies your workspace across repos while keeping strict per-repo scope for retrieval and memory.

![Dark themed UI with glassmorphism](https://img.shields.io/badge/theme-glassmorphism-6366f1)

## Features

- **Agentic RAG pipeline** — Claude autonomously decides which tools to call (up to 10 rounds per query)
- **Hybrid search** — vector similarity + BM25 keyword search, fused with Reciprocal Rank Fusion, reranked with Voyage Rerank-2, expanded with neighbor chunks. Optional query rewriting + multi-query expansion on the UI path
- **Fast vs Full search modes** — MCP uses a fast path that skips LLM-driven query enrichment; the UI uses the full path for higher recall
- **Centralized LLM client** — task → model routing (Haiku for routing/metadata, Sonnet/Opus for synthesis) with prompt caching across rewrite, multi-query, and tool-use turns
- **Document ingestion** — parse, chunk, extract metadata (topics/keywords), embed, and store with deduplication
- **Notes & per-folder context** — save snippets and pin context that the agent always sees
- **API keys** — scoped programmatic access; external apps can push files into your KB via `/api/drop`
- **Eval harness** — IR metrics (recall, MRR, nDCG) plus optional RAGAS, gated against a baseline on every PR. See [`backend/eval/README.md`](backend/eval/README.md)
- **Runtime metrics + stage timings** — every retrieval emits search, rerank, cache-hit, and per-stage latency records
- **Text-to-SQL** — natural language queries against document metadata
- **Web search** — falls back to Tavily when documents don't have the answer
- **Folder organization** — nested folders (Google Drive-style) with drag-and-drop
- **MCP server** — expose your knowledge base to Claude Code, Cursor, or any MCP client
- **Streaming responses** — real-time token delivery via Server-Sent Events
- **Multi-tenant** — all data scoped by user with Supabase Auth + Row Level Security
- **Self-hosted** — deploy with Docker Compose behind Traefik or any reverse proxy

## Recommended workflow (get the richest briefing)

Kioku is centered on repos, but a repo's code alone rarely captures the whole
ecosystem it lives in — the external systems it talks to, the specs, the design
decisions. The **ideal order** gives Claude that context up front:

1. **Create the folder in the web UI** for the repo you're about to wire.
2. **Seed it with ecosystem context** — upload docs (PDFs, Markdown, specs,
   architecture notes) and/or **connect Notion sync**.
3. **`cd` into the repo and run `kioku init`.** During generation Claude calls
   `read_folder_documents` and folds those uploaded docs into both the briefing
   and the detailed architecture doc — so you get a briefing that understands
   your whole ecosystem, not just this repo's code.

Already ran `kioku init` on a bare folder? Add the docs later and re-run
`kioku init --force` to regenerate with the new context.

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────────────┐
│   Frontend   │     │                  Backend                     │
│  React + MUI │────▶│  FastAPI                                     │
│  Vite + TS   │ SSE │                                              │
└─────────────┘     │  ┌─────────┐  ┌────────────────────────────┐ │
                     │  │  Auth   │  │     Agentic RAG Pipeline    │ │
┌─────────────┐     │  │ (JWT)   │  │                            │ │
│  MCP Client  │     │  └─────────┘  │  Claude ──▶ Tool Router    │ │
│ Claude Code  │────▶│               │    │                       │ │
│   Cursor     │ SSE │               │    ├─ knowledge_base_search│ │
└─────────────┘     │               │    ├─ query_documents_meta  │ │
                     │               │    └─ web_search            │ │
                     │               └────────────────────────────┘ │
                     │                           │                  │
                     │  ┌────────────────────────▼────────────────┐ │
                     │  │            Services                     │ │
                     │  │  Ingestion · Search · Rerank · Embed    │ │
                     │  │  Text-to-SQL · Web Search · Metadata    │ │
                     │  └────────────────────────┬────────────────┘ │
                     └───────────────────────────┼──────────────────┘
                                                 │
                     ┌───────────────────────────▼──────────────────┐
                     │              Supabase (PostgreSQL)            │
                     │  documents (pgvector) · conversations        │
                     │  messages · folders · RPC functions           │
                     └──────────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19, TypeScript, Material-UI, Vite |
| Backend | Python, FastAPI, Uvicorn |
| AI | Claude (Opus / Sonnet / Haiku) via a centralized client with task→model routing and prompt caching; Voyage AI (embeddings + Rerank-2) |
| Search | pgvector (cosine similarity), PostgreSQL full-text search, RRF fusion, neighbor expansion |
| Database | Supabase (PostgreSQL + Auth + RLS) |
| Web Search | Tavily API |
| Document Parsing | Docling (PDF, DOCX, HTML, Markdown, text) |
| MCP | FastMCP over SSE |
| Eval | IR metrics (recall, MRR, nDCG) + optional RAGAS, gated in CI |
| Observability | Per-request runtime metrics + per-stage timings |
| Deployment | Docker Compose, Nginx |

## Prerequisites

- [Supabase](https://supabase.com) project (free tier works)
- [Anthropic API key](https://console.anthropic.com)
- [Voyage AI API key](https://www.voyageai.com)
- [Tavily API key](https://tavily.com) (for web search)
- Python 3.10+ with [uv](https://docs.astral.sh/uv/)
- Node.js 20+

## Setup

### 1. Database

Run the schema in your Supabase SQL Editor:

```sql
-- backend/db/schema.sql contains everything:
-- tables: conversations, messages, folders, documents
-- indexes: HNSW vector index, GIN full-text index
-- RLS policies for multi-tenancy
-- RPC functions: match_documents, keyword_search, execute_readonly_query
```

See [`backend/db/schema.sql`](backend/db/schema.sql) for the full schema.

### 2. Backend

```bash
cd backend
cp .env.example .env
# Fill in your API keys in .env
```

```env
ANTHROPIC_API_KEY=sk-ant-...
VOYAGE_API_KEY=pa-...
TAVILY_API_KEY=tvly-...
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=eyJ...
SUPABASE_JWT_SECRET=your-jwt-secret
MCP_API_KEY=any-secret-string
```

```bash
uv sync
uv run uvicorn main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
cp .env.example .env
# Fill in your Supabase public keys in .env
```

```env
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_ANON_KEY=eyJ...
```

```bash
npm install
npm run dev
```

The app will be available at `http://localhost:5173` (Vite proxies API requests to the backend).

### 4. MCP Server (optional)

```bash
cd backend
uv run python mcp_server.py
# Runs on port 8001
```

Connect from Claude Code or any MCP client:

```json
{
  "mcpServers": {
    "agentic-rag": {
      "type": "sse",
      "url": "http://localhost:8001/sse",
      "headers": {
        "Authorization": "Bearer your-mcp-api-key"
      }
    }
  }
}
```

## Docker Deployment

```bash
# Backend + MCP environment variables
export ANTHROPIC_API_KEY=...
export VOYAGE_API_KEY=...
export TAVILY_API_KEY=...
export SUPABASE_URL=...
export SUPABASE_SERVICE_KEY=...
export SUPABASE_JWT_SECRET=...
export MCP_API_KEY=...

# Frontend build args (Vite bakes these into the JS bundle at build time)
export VITE_SUPABASE_URL=...
export VITE_SUPABASE_ANON_KEY=...

docker compose up -d --build
```

Three containers:
- **backend** — FastAPI on port 8000
- **mcp-server** — MCP over SSE on port 8001
- **frontend** — Nginx on port 80 (proxies `/api` requests to backend)

The frontend Nginx config handles both SPA routing and reverse-proxying API requests to the backend container, so everything runs through a single port.

For production behind Traefik, add labels to `docker-compose.yml` for your domain routing.

## How It Works

### Document Ingestion

```
File Upload → Docling Parser → SHA-256 Dedup Check
    → Recursive Chunking (2048 chars, 200 overlap)
    → Metadata Extraction (Claude Haiku: topic + keywords)
    → Voyage Embeddings (1024 dimensions)
    → Store in PostgreSQL with pgvector
```

Supported formats: PDF, DOCX, HTML, Markdown, plain text.

### Query Pipeline

```
User Question → Claude Haiku (agent loop, max 10 rounds)
    │
    ├─ knowledge_base_search
    │    → Voyage embed query
    │    → Vector search (cosine similarity, top 20)
    │    → Keyword search (BM25, top 20)
    │    → RRF Fusion
    │    → Voyage Rerank-2 (top K)
    │
    ├─ query_documents_metadata
    │    → Claude generates SELECT SQL
    │    → Regex validation (no writes)
    │    → Execute via Supabase RPC
    │
    └─ web_search
         → Tavily API
         → Return top results

    → Claude synthesizes final answer
    → Stream tokens via SSE
```

### MCP Integration

The MCP server exposes `knowledge_base_search` and `query_documents_metadata` as tools. This lets you connect your knowledge base to external AI tools:

- **Claude Code** — query work documents without leaving the terminal
- **Cursor** — search your knowledge base while coding
- **Any MCP client** — standard protocol, works with any compatible tool

Use folders to scope what gets searched — e.g., connect only your "Work" folder to Claude Code.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat` | Stream agentic RAG response (SSE) |
| `GET` | `/api/conversations` | List conversations |
| `POST` | `/api/conversations` | Create conversation |
| `GET` | `/api/conversations/:id` | Get conversation with messages |
| `DELETE` | `/api/conversations/:id` | Delete conversation |
| `POST` | `/api/documents/upload` | Upload document |
| `GET` | `/api/documents` | List documents (optional folder filter) |
| `GET` | `/api/documents/ingestion-status` | Poll ingestion progress |
| `GET` | `/api/documents/:filename/download` | Download original file |
| `GET` | `/api/documents/filters` | Get available topics and keywords |
| `PATCH` | `/api/documents/:filename/move` | Move document to folder |
| `DELETE` | `/api/documents/:filename` | Delete document and chunks |
| `GET` | `/api/folders` | List folders |
| `POST` | `/api/folders` | Create folder |
| `PATCH` | `/api/folders/:id` | Rename folder |
| `DELETE` | `/api/folders/:id` | Delete folder (cascades subfolders) |
| `GET` | `/api/folders/:id/breadcrumbs` | Get folder path |
| `GET` | `/api/notes` | List notes |
| `DELETE` | `/api/notes/:note_id` | Delete a note |
| `GET` | `/api/context` | List per-folder pinned context |
| `DELETE` | `/api/context/clear` | Clear all pinned context |
| `DELETE` | `/api/context/:context_id` | Remove one pinned context entry |
| `GET` | `/api/api-keys` | List API keys |
| `POST` | `/api/api-keys` | Create a scoped API key |
| `DELETE` | `/api/api-keys/:key_id` | Revoke an API key |
| `POST` | `/api/drop` | External file ingest (API-key auth, used by `/api/api-keys`) |
| `POST` | `/api/evaluate` | Run an IR / RAGAS evaluation request |
| `GET` | `/api/health` | Health check |

All endpoints except `/api/health` and `/api/drop` require a valid Supabase JWT in the `Authorization` header. `/api/drop` accepts a Bearer token issued via `/api/api-keys`.

## Project Structure

```
├── backend/
│   ├── main.py                 # FastAPI app, route registration
│   ├── auth.py                 # JWT verification (Supabase JWKS)
│   ├── mcp_server.py           # MCP server (SSE transport)
│   ├── routes/
│   │   ├── chat.py             # Chat endpoint with SSE streaming
│   │   ├── conversations.py    # Conversation CRUD
│   │   ├── documents.py        # Document upload, list, delete, move, status, download
│   │   ├── folders.py          # Folder CRUD + breadcrumbs
│   │   ├── notes.py            # Saved snippets
│   │   ├── context.py          # Per-folder pinned context
│   │   ├── api_keys.py         # Scoped API keys for programmatic access
│   │   ├── drop.py             # External file ingest (API-key auth)
│   │   └── evaluation.py       # On-demand IR / RAGAS evaluation
│   ├── services/
│   │   ├── rag.py              # Agentic loop (tool dispatch + streaming)
│   │   ├── tools.py            # Tool definitions for Claude
│   │   ├── search.py           # Hybrid search + RRF + reranking + neighbor expansion (fast/full modes)
│   │   ├── query.py            # Query rewriting + multi-query expansion (full mode)
│   │   ├── llm.py              # Centralized Anthropic client: task→model routing + prompt cache
│   │   ├── embeddings.py       # Voyage AI embedding client
│   │   ├── rerank.py           # Voyage Rerank-2
│   │   ├── ingestion.py        # Orchestrates parsing → chunking → embedding
│   │   ├── parser.py           # Docling document parser
│   │   ├── chunker.py          # Recursive text splitter
│   │   ├── metadata.py         # Topic/keyword extraction (Claude)
│   │   ├── scope.py            # Folder / context scoping helpers
│   │   ├── metrics.py          # Per-request runtime metrics (search, rerank, cache-hit)
│   │   ├── timing.py           # Stage timing instrumentation
│   │   ├── evaluation.py       # RAGAS wrapper (faithfulness, relevancy, ctx precision/recall)
│   │   ├── web_search.py       # Tavily web search
│   │   └── text_to_sql.py      # NL → SQL generation + execution
│   ├── eval/                   # Eval harness (see backend/eval/README.md)
│   │   ├── runner.py           # Run eval + emit aggregate report + gate against baseline
│   │   ├── ir_metrics.py       # Recall@k, MRR, nDCG@k
│   │   ├── baseline.json       # Per-metric min + tolerance (regression floor)
│   │   ├── update_baseline.py  # Re-pin baseline from latest run
│   │   └── run_local.sh        # End-to-end loop against local Supabase
│   └── db/
│       ├── client.py           # Supabase client singleton
│       ├── schema.sql          # Full database schema (dumped from Supabase)
│       ├── api_keys_schema.sql # API keys table (loaded separately)
│       ├── local_setup.sql     # Local-dev seed user + RLS shortcuts
│       ├── clean_schema.py     # Strip auth-managed bits from supabase db dump
│       └── seed.py             # Seed example documents for local dev
├── frontend/
│   ├── src/
│   │   ├── pages/              # ChatPage, DocumentsPage, LoginPage
│   │   ├── components/         # Sidebar, ChatArea, FolderTree, etc.
│   │   ├── hooks/              # useAuth, useConversations, useDocuments
│   │   └── lib/                # API client, Supabase client
│   ├── nginx.conf              # SPA routing for production
│   └── Dockerfile
└── docker-compose.yml
```

## License

MIT
