"""Tool definitions and dispatch for agentic RAG."""

import json

from langsmith import traceable

from services.embeddings import embed_query
from services.search import search_documents
from services.text_to_sql import generate_and_execute_sql
from services.web_search import web_search

TOOL_DEFINITIONS = [
    {
        "name": "knowledge_base_search",
        "description": (
            "Search the user's uploaded document knowledge base using hybrid "
            "vector + keyword search. Use this for questions about content in "
            "the user's documents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant document chunks.",
                },
                "created_after": {
                    "type": "string",
                    "description": (
                        "Optional ISO date (YYYY-MM-DD). Only search content created "
                        "on/after this date — use when the user asks about a specific "
                        "period ('last month', 'since March', 'recent')."
                    ),
                },
                "created_before": {
                    "type": "string",
                    "description": (
                        "Optional ISO date (YYYY-MM-DD). Only search content created "
                        "on/before this date — use for historical questions "
                        "('back in January', 'before the migration')."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_documents_metadata",
        "description": (
            "Query structured metadata about the user's uploaded documents using "
            "natural language. Use this for questions like 'how many documents do I have', "
            "'what topics are covered', 'list my PDFs', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Natural language question about document metadata.",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Search the web for information not found in the user's knowledge base. "
            "Use this when the knowledge base doesn't contain relevant information "
            "to answer the user's question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The web search query.",
                },
            },
            "required": ["query"],
        },
    },
]


@traceable(name="execute_tool", run_type="tool")
def execute_tool(
    tool_name: str,
    tool_input: dict,
    user_id: str,
    topic: str | None = None,
    keyword: str | None = None,
    fast_mode: bool = False,
    scope_folder_ids: list[str] | None = None,
    scope_filename: str | None = None,
) -> str:
    """Execute a tool call and return the result as a string."""
    if tool_name == "knowledge_base_search":
        query = tool_input["query"]
        embedding = embed_query(query)
        results = search_documents(
            embedding,
            query_text=query,
            user_id=user_id,
            topic=topic,
            keyword=keyword,
            fast_mode=fast_mode,
            folder_ids=scope_folder_ids,
            source_filename=scope_filename,
            created_after=tool_input.get("created_after"),
            created_before=tool_input.get("created_before"),
        )
        if not results:
            return "No relevant documents found in the knowledge base."
        chunks = []
        for r in results:
            source = (r.get("metadata") or {}).get("source_filename", "unknown")
            # Date in the header lets the model weigh freshness and cite
            # as-of dates — retrieval alone can't resolve conflicting facts.
            date = str(r.get("created_at") or "")[:10]
            header = f"[Source: {source} — {date}]" if date else f"[Source: {source}]"
            chunks.append(f"{header}\n{r['content']}")
        return "\n\n---\n\n".join(chunks)

    if tool_name == "query_documents_metadata":
        result = generate_and_execute_sql(tool_input["question"], user_id)
        if result["error"]:
            return f"Query failed: {result['error']}"
        if not result["results"]:
            return "No results found."
        return f"SQL: {result['sql']}\nResults: {json.dumps(result['results'], default=str)}"

    if tool_name == "web_search":
        results = web_search(tool_input["query"])
        if not results:
            return "Web search returned no results."
        parts = []
        for r in results:
            parts.append(f"**{r['title']}**\n{r['url']}\n{r['content']}")
        return "\n\n---\n\n".join(parts)

    return f"Unknown tool: {tool_name}"
