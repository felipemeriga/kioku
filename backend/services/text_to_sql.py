"""Text-to-SQL: generate and execute read-only queries against document metadata."""

import logging
import re

from langsmith import traceable

from db.client import get_supabase
from services.llm import Task, complete

logger = logging.getLogger(__name__)

DOCUMENTS_SCHEMA = """Table: documents
Columns:
  - id: uuid (primary key)
  - content: text (document chunk text)
  - metadata: jsonb (contains "source_filename", "chunk_index", "total_chunks")
  - user_id: uuid (owner)
  - source_filename: text (original filename)
  - source_type: text (pdf, docx, html, markdown, text)
  - content_hash: text (SHA-256 of original file)
  - status: text (processing, completed, failed)
  - created_at: timestamptz
  - last_updated: timestamptz (last content change; not the last sync)

Notes:
  - Multiple rows per file (one per chunk). Use DISTINCT source_filename to count files.
  - To extract a jsonb field as text use ->> (e.g. metadata->>'source_filename').
  - NEVER use ILIKE or text operators directly on jsonb columns.
    Always use ->> to extract as text first.
  - source_type can be: pdf, docx, html, markdown, text, json, yaml, image, audio
  - root_folder_id: uuid (scope — root folder this document belongs to)
  - Always filter by user_id = '{user_id}' to scope to the current user.
  - If root_folder_id filter is provided, also add: AND root_folder_id = '{root_folder_id}'"""

SQL_GENERATION_PROMPT = """You are a SQL expert. Generate a PostgreSQL SELECT query to answer the \
user's question.

{schema}

Rules:
- ONLY generate SELECT statements. Never INSERT, UPDATE, DELETE, DROP, or any DDL.
- Always include WHERE user_id = '{user_id}' to scope results to the current user.
- If a root_folder_id is provided, also filter: AND root_folder_id = '{root_folder_id}'.
- Return ONLY the SQL query, no explanation, no markdown fences.
- Keep queries simple and efficient.

User question: {question}"""


def _validate_sql(sql: str) -> bool:
    """Validate that the SQL is a safe read-only SELECT."""
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned.upper().startswith("SELECT"):
        return False
    forbidden = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXECUTE)\b",
        re.IGNORECASE,
    )
    return not forbidden.search(cleaned)


def _is_user_scoped(sql: str, user_id: str) -> bool:
    """True if the query filters on the caller's own user_id (verbatim).

    The generation prompt instructs `WHERE user_id = '<user_id>'`; this enforces
    it structurally so the RLS-bypassing RPC can't be coerced (prompt injection
    via the question, or a model lapse) into reading another user's rows."""
    return re.search(rf"user_id\s*=\s*'{re.escape(user_id)}'", sql, re.IGNORECASE) is not None


@traceable(name="generate_and_execute_sql", run_type="chain")
def generate_and_execute_sql(
    question: str, user_id: str, root_folder_id: str | None = None
) -> dict:
    """Generate SQL from natural language and execute it.

    Returns dict with keys: sql (the generated query), results (list of rows),
    error (string if failed).
    """
    schema = DOCUMENTS_SCHEMA.format(user_id=user_id, root_folder_id=root_folder_id or "N/A")
    prompt = SQL_GENERATION_PROMPT.format(
        schema=schema,
        user_id=user_id,
        root_folder_id=root_folder_id or "",
        question=question,
    )

    try:
        response = complete(
            task=Task.TEXT_TO_SQL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=256,
        )
        sql = response.content[0].text.strip()

        # Strip markdown fences if present
        if sql.startswith("```"):
            sql = re.sub(r"^```(?:sql)?\n?", "", sql)
            sql = re.sub(r"\n?```$", "", sql)
            sql = sql.strip()

        # Strip trailing semicolons (breaks when wrapped in subquery)
        sql = sql.rstrip(";").strip()

        if not _validate_sql(sql):
            return {"sql": sql, "results": [], "error": "Generated SQL failed safety validation"}

        # Enforce user-scoping STRUCTURALLY, not just via the prompt. The RPC is
        # SECURITY DEFINER (bypasses RLS), so a prompt-injected or malformed query
        # that drops/changes the user filter could read another user's rows.
        # Require the caller's own user_id predicate to be present verbatim.
        if not _is_user_scoped(sql, user_id):
            logger.warning("Text-to-SQL rejected: generated query not scoped to caller's user_id")
            return {"sql": sql, "results": [], "error": "Generated SQL is not user-scoped"}

        sb = get_supabase()
        result = sb.rpc("execute_readonly_query", {"query_text": sql}).execute()

        return {"sql": sql, "results": result.data, "error": None}
    except Exception as e:
        logger.warning("Text-to-SQL failed", exc_info=True)
        return {"sql": "", "results": [], "error": str(e)}
