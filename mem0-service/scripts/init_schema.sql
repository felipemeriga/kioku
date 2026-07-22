-- Idempotent bootstrap for the self-hosted mem0 service.
-- The mem0 service also runs this at startup (see app/store.py::_ensure_schema),
-- but it's kept here so the schema can be provisioned manually against a managed
-- Postgres (e.g. Supabase) if needed.
CREATE SCHEMA IF NOT EXISTS mem0;
CREATE EXTENSION IF NOT EXISTS vector;
