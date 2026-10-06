// Demo data the design-system previews render with. Shapes follow src/lib/api.ts.
const now = Date.now();
const ago = (min: number) => new Date(now - min * 60000).toISOString();

export const folders = [
  { id: "f-kioku", name: "kioku", parent_id: null, user_id: "u-demo", created_at: ago(60 * 24 * 40), kind: "repo" },
  { id: "f-obol", name: "obol-ledger", parent_id: null, user_id: "u-demo", created_at: ago(60 * 24 * 21), kind: "repo" },
  { id: "f-research", name: "Research notes", parent_id: null, user_id: "u-demo", created_at: ago(60 * 24 * 12), kind: "folder" },
  { id: "f-wiki", name: "Eng wiki (Notion)", parent_id: null, user_id: "u-demo", created_at: ago(60 * 24 * 5), kind: "folder" },
  { id: "f-rag", name: "RAG papers", parent_id: "f-research", user_id: "u-demo", created_at: ago(60 * 24 * 10), kind: "folder" },
  { id: "f-evals", name: "Evals", parent_id: "f-research", user_id: "u-demo", created_at: ago(60 * 24 * 9), kind: "folder" },
];

const doc = (name: string, type: string, chunks: number, status: string, min: number, folder: string | null) => ({
  source_filename: name, source_type: type, has_file: true, chunks, status, created_at: ago(min), folder_id: folder,
});
export const documents = [
  doc("hybrid_search_rrf.md", "markdown", 18, "completed", 42, "f-research"),
  doc("hnsw_vs_ivfflat.pdf", "pdf", 64, "completed", 60 * 5, "f-rag"),
  doc("chunking_strategies.md", "markdown", 23, "completed", 60 * 26, "f-rag"),
  doc("voyage_embeddings.docx", "docx", 31, "processing", 3, "f-research"),
  doc("system_design_principles.txt", "text", 12, "completed", 60 * 24 * 3, "f-research"),
  doc("ragas_eval_report.html", "html", 9, "failed", 60 * 24 * 4, "f-evals"),
  doc("architecture.md", "markdown", 14, "completed", 60 * 2, "f-kioku"),
  doc("ingest_worker.py", "code", 7, "completed", 60 * 3, "f-kioku"),
  doc("Onboarding — backend.md", "notion", 11, "completed", 60 * 8, "f-wiki"),
];

export const conversations = [
  { id: "c-1", title: "How does reranking change recall@10?", created_at: ago(20), updated_at: ago(4) },
  { id: "c-2", title: "Explain the ingestion pipeline stages", created_at: ago(60 * 5), updated_at: ago(60 * 5) },
  { id: "c-3", title: "obol-ledger: refund posting flow", created_at: ago(60 * 24 * 2), updated_at: ago(60 * 24 * 2) },
  { id: "c-4", title: "pgvector index tuning", created_at: ago(60 * 24 * 6), updated_at: ago(60 * 24 * 6) },
];

export const debugTrace = {
  model: "claude-sonnet",
  reasoning: [
    { round: 1, text: "The question is about reranking impact. Search the eval notes and the RRF doc first." },
    { round: 2, text: "Two eval runs found; compare recall@10 with and without the reranker." },
  ],
  tool_calls: [
    { round: 1, name: "search_documents", input: { query: "reranker recall@10", k: 8 }, result_preview: "8 chunks · top: ragas_eval_report.html (0.91)" },
    { round: 2, name: "read_document", input: { filename: "hybrid_search_rrf.md" }, result_preview: "## Reciprocal Rank Fusion\nRRF merges BM25 and vector ranks…" },
  ],
  retrieval: [
    { query: "reranker recall@10", source: "ragas_eval_report.html", source_type: "html", rerank_score: 0.91, similarity: 0.82, content: "With the cross-encoder reranker, recall@10 rose from 0.71 to 0.84 on the golden set." },
    { query: "reranker recall@10", source: "hybrid_search_rrf.md", source_type: "markdown", symbol: null, rerank_score: 0.77, similarity: 0.79, content: "RRF with k=60 fuses BM25 and pgvector results before reranking." },
  ],
};

export const messages = [
  { id: "m-1", role: "user", content: "How much does the reranker improve recall@10 on our golden set?", created_at: ago(6) },
  {
    id: "m-2", role: "assistant", created_at: ago(5), debug: debugTrace,
    content:
      "On the golden set, adding the cross-encoder reranker lifts **recall@10 from 0.71 to 0.84** (+13 pts).\n\n" +
      "| Pipeline | recall@10 | MRR |\n|---|---|---|\n| BM25 + vector (RRF) | 0.71 | 0.58 |\n| + reranker | **0.84** | **0.69** |\n\n" +
      "The fusion step is unchanged:\n\n```python\ndef rrf(ranks, k=60):\n    return sum(1 / (k + r) for r in ranks)\n```\n\nSources: `ragas_eval_report.html`, `hybrid_search_rrf.md`.",
  },
  { id: "m-3", role: "user", content: "And latency?", created_at: ago(4) },
  { id: "m-4", role: "assistant", created_at: ago(4), content: "p50 grows by ~120 ms (rerank of 50 candidates). Worth it for chat; keep it off for the MCP `search` tool where agents batch queries." },
];

const sec = (content: unknown, status = "auto", provenance = "auto", min = 90) => ({
  status, content, provenance, updated_at: ago(min), updated_by: provenance === "auto" ? null : "felipe",
});
export const briefing = {
  folder: { id: "f-kioku", name: "kioku", kind: "repo" },
  schema_version: 3,
  last_generated_at: ago(90),
  freshness: { head_sha: "ba12918c4e1", commits_behind: 2, stale_sections: ["activity"], changed_files: 5, checked_at: ago(12) },
  index_status: { git_updates_at: ago(12), head_sha: "ba12918c4e1", graph_at: ago(95), graph_sha: "ba12918", graph_nodes: 1842, graph_edges: 5310, semantic_code_at: ago(95) },
  sections: {
    overview: sec("Kioku (記憶) is a second brain for your repos: it ingests documents, Notion pages and code, keeps a per-repo briefing fresh, and answers questions over all of it via chat, CLI and MCP."),
    architecture: sec({
      Frontend: "React 19 + MUI 7 SPA (Vite), served by nginx.",
      Backend: "FastAPI — auth, documents, chat streaming (SSE), briefing API.",
      Worker: "arq on Redis — parse → chunk → embed → store.",
      Storage: "Supabase Postgres + pgvector; files in Supabase Storage.",
      Memory: "Self-hosted mem0 per repo folder.",
    }, "pinned", "user_ui"),
    preferences: sec(["Prefer small PRs with a test per fix.", "Never call the LLM inside the ingestion worker's hot loop."]),
    important_files: sec(["backend/main.py — API entry", "backend/queue/jobs.py — ingestion jobs", "frontend/src/theme.ts — brand tokens", "cli/kioku/__main__.py — CLI"]),
    how_it_runs: sec("docker compose -f docker-compose.dev.yml up\ncd frontend && npm run dev"),
    deployment: sec("Self-hosted on the hive cluster; one compose file per service under deploy/hive/kioku.", "hybrid", "agent_mcp"),
    dependencies: sec({ frontend: ["react 19", "@mui/material 7", "react-markdown 10"], backend: ["fastapi", "arq", "voyageai", "anthropic"] }),
    activity: sec(["#76 fix(chat): preserve user line breaks", "#75 feat(briefing): index status cards", "decision: keep reranker on for chat only"], "auto", "auto", 600),
  },
};

export const documentation = {
  documentation: {
    abstract: "How Kioku turns a repository into a briefing an agent can read in one pass.",
    generated_at: ago(95),
    content:
      "# Kioku — repository documentation\n\n## Ingestion\nEvery upload becomes an **ingestion task** that moves through `parsing → chunking → embedding → storing`.\n\n## Retrieval\nHybrid search fuses BM25 and pgvector with RRF, then reranks.\n\n```bash\nkioku init\nkioku ask \"where is the chunker?\"\n```\n",
  },
};

export const ingestionTasks = [
  { id: "t-1", user_id: "u-demo", filename: "voyage_embeddings.docx", folder_id: "f-research", stage: "embedding", stage_detail: "batch 3/5", error_message: null, chunks_total: 31, chunks_done: 19, duplicate: false, document_ids: [], created_at: ago(3), updated_at: ago(0) },
  { id: "t-2", user_id: "u-demo", filename: "hnsw_vs_ivfflat.pdf", folder_id: "f-rag", stage: "completed", stage_detail: null, error_message: null, chunks_total: 64, chunks_done: 64, duplicate: false, document_ids: ["d-2"], created_at: ago(9), updated_at: ago(7) },
  { id: "t-3", user_id: "u-demo", filename: "ragas_eval_report.html", folder_id: "f-evals", stage: "error", stage_detail: null, error_message: "Parser returned no text (scanned page?)", chunks_total: null, chunks_done: 0, duplicate: false, document_ids: [], created_at: ago(11), updated_at: ago(10) },
  { id: "t-4", user_id: "u-demo", filename: "chunking_strategies.md", folder_id: "f-rag", stage: "duplicate", stage_detail: null, error_message: null, chunks_total: 0, chunks_done: 0, duplicate: true, document_ids: [], created_at: ago(12), updated_at: ago(12) },
];

export const notionConfig = { id: "n-1", root_folder_id: "f-wiki", notion_page_id: "pg-1", notion_page_title: "Engineering Wiki", fast_poll_interval_min: 15, last_fast_sync_at: ago(14), last_full_sync_at: ago(60 * 20), last_error: null };
export const notionJob = { id: "j-1", user_id: "u-demo", kind: "notion_sync", source_ref: "pg-1", parent_job_id: null, root_folder_id: "f-wiki", status: "running", current_step: "Syncing pages", total_batches: 4, processed_batches: 2, total_pages: 38, processed_pages: 23, error: null, started_at: ago(2), completed_at: null };

export const memoriesRules = [
  { id: "mem-1", memory: "Prefer small PRs with a test per fix.", metadata: { scope: "eternal", category: "preference", tags: ["workflow"], written_by: "felipe" }, created_at: ago(60 * 24 * 9), updated_at: ago(60 * 24 * 9) },
  { id: "mem-2", memory: "Reranker stays on for chat, off for the MCP search tool (latency).", metadata: { scope: "eternal", category: "decision", tags: ["retrieval"], written_by: "claude-code" }, created_at: ago(60 * 24 * 2), updated_at: ago(60 * 24 * 2) },
];
export const memoriesRecent = [
  { id: "mem-3", memory: "Chunker splits markdown on headings first, then 800-token windows with 100 overlap.", metadata: { scope: "episodic", category: "finding", tags: ["ingestion"], written_by: "claude-code" }, created_at: ago(60 * 3), updated_at: ago(60 * 3) },
  { id: "mem-4", memory: "Notion sync stalls when a page has >100 child blocks — paginate block children.", metadata: { scope: "episodic", category: "issue", tags: ["notion"], written_by: "kioku-cli" }, created_at: ago(60 * 7), updated_at: ago(60 * 7) },
  { id: "mem-5", memory: "Session: added index status cards to the briefing panel.", metadata: { scope: "episodic", category: "session", tags: [], written_by: "claude-code" }, created_at: ago(60 * 26), updated_at: ago(60 * 26) },
];

export const apiKeys = [
  { id: "k-1", name: "Claude Code — laptop", scope_folder_id: "f-kioku", scope_folder_name: "kioku", created_at: ago(60 * 24 * 14) },
  { id: "k-2", name: "CI agent", scope_folder_id: "f-obol", scope_folder_name: "obol-ledger", created_at: ago(60 * 24 * 3) },
];

export const documentContent = (filename: string) => ({
  source_filename: filename,
  source_type: "markdown",
  metadata: { topic: "retrieval", keywords: ["rrf", "bm25", "pgvector"] },
  chunk_count: 18,
  folder_id: "f-research",
  status: "completed",
  created_at: ago(42),
  viewable_as: "markdown",
  file_url: null,
  bucket: "documents",
  content:
    "# Hybrid search with RRF\n\nKioku runs **BM25** (Postgres `tsvector`) and **vector search** (pgvector, HNSW) in parallel, then fuses the two rankings with *Reciprocal Rank Fusion*.\n\n## Why RRF\n- No score calibration between retrievers\n- One knob: `k` (we use 60)\n\n```python\ndef rrf(ranks, k=60):\n    return sum(1 / (k + r) for r in ranks)\n```\n\n> The fused list is then reranked by a cross-encoder before it reaches the model.\n",
});

export const filters = { topics: ["retrieval", "ingestion", "evals", "infra"], keywords: ["rrf", "bm25", "pgvector", "hnsw", "reranker", "notion"] };
export const githubRepos = [
  { owner: "felipemeriga", name: "kioku", full_name: "felipemeriga/kioku", private: false, description: "Second brain for your repos.", pushed_at: ago(60), url: "https://github.com/felipemeriga/kioku" },
  { owner: "felipemeriga", name: "obol-ledger", full_name: "felipemeriga/obol-ledger", private: true, description: "Double-entry ledger service.", pushed_at: ago(60 * 24), url: null },
];
