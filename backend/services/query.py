"""Query rewriting: expand and reformulate queries for better retrieval."""

from langsmith import traceable

from services.llm import Task, complete

REWRITE_PROMPT = """Rewrite the following search query to improve document retrieval.
Your goal is to expand the query with synonyms, related terms, and alternative phrasings
while preserving the original intent.

Return ONLY the rewritten query, nothing else. Keep it under 200 words.

Original query: {query}"""

MULTI_QUERY_PROMPT = """Generate 3 different search queries that capture different angles
of the user's original question. Each query should use different terms and phrasing
to maximize recall across a document knowledge base.

Return ONLY the queries, one per line, no numbering or bullets.

Original question: {query}"""


@traceable(name="rewrite_query", run_type="chain")
def rewrite_query(query: str) -> str:
    """Rewrite a query for better retrieval using Claude Haiku."""
    response = complete(
        task=Task.QUERY_REWRITE,
        messages=[{"role": "user", "content": REWRITE_PROMPT.format(query=query)}],
        max_tokens=256,
    )
    return response.content[0].text.strip()


@traceable(name="generate_multi_queries", run_type="chain")
def generate_multi_queries(query: str) -> list[str]:
    """Generate multiple query variants to improve retrieval recall."""
    response = complete(
        task=Task.MULTI_QUERY,
        messages=[{"role": "user", "content": MULTI_QUERY_PROMPT.format(query=query)}],
        max_tokens=256,
    )
    text = response.content[0].text.strip()
    queries = [line.strip() for line in text.split("\n") if line.strip()]
    return queries[:3]
