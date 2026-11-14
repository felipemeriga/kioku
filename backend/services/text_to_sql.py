"""Text-to-SQL: generate and execute read-only queries against document metadata."""

import logging
import re

from langsmith import traceable

from db.client import get_supabase
from services.llm import Task, complete
from services.metadata_sql import scoped_metadata_sql

logger = logging.getLogger(__name__)

DOCUMENTS_SCHEMA = """Table: documents
Columns:
  - id: uuid (primary key)
  - metadata: jsonb (contains "source_filename", "chunk_index", "total_chunks")
  - user_id: uuid (owner; authorization is applied by the backend)
  - folder_id: uuid (containing folder)
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
  - Caller ownership, authorized folders and selected-file filters are imposed by the backend.
    Do not choose or override authorization IDs."""

SQL_GENERATION_PROMPT = """You are a SQL expert. Generate a PostgreSQL SELECT query to answer the \
user's question.

{schema}

Rules:
- ONLY generate SELECT statements. Never INSERT, UPDATE, DELETE, DROP, or any DDL.
- The backend applies authorization scope. Do not invent or choose owner/folder IDs.
- Return ONLY the SQL query, no explanation, no markdown fences.
- Query only documents metadata columns; never select content or use SELECT *.
- Use a single SELECT without joins, subqueries, CTEs or arbitrary functions.
- Keep queries simple and efficient.

User question: {question}"""


@traceable(name="generate_and_execute_sql", run_type="chain")
def generate_and_execute_sql(
    question: str,
    user_id: str,
    root_folder_id: str | None = None,
    *,
    folder_ids: list[str] | None = None,
    filename: str | None = None,
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

        try:
            sql = scoped_metadata_sql(
                sql, user_id, root_folder_id, folder_ids=folder_ids, filename=filename
            )
        except ValueError:
            return {"sql": "", "results": [], "error": "Unsupported document metadata query"}

        sb = get_supabase()
        result = sb.rpc("execute_readonly_query", {"query_text": sql}).execute()

        return {"sql": sql, "results": result.data, "error": None}
    except Exception:
        logger.warning("Document metadata query did not complete")
        return {"sql": "", "results": [], "error": "Document metadata query did not complete"}
