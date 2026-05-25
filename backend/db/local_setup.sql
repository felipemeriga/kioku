-- backend/db/local_setup.sql
-- One-time local-DB setup that lives outside the public schema dump.
-- Apply AFTER schema.sql against a fresh `supabase start` instance:
--
--   psql postgresql://postgres:postgres@127.0.0.1:54322/postgres -f backend/db/local_setup.sql
--
-- Creates the Supabase Storage buckets that the backend's ingestion code
-- writes to (documents / images / audio). These exist in prod via the
-- Supabase dashboard; locally we materialize them by inserting into
-- storage.buckets directly.

INSERT INTO storage.buckets (id, name, public, file_size_limit)
VALUES
    ('documents', 'documents', false, NULL),
    ('images',    'images',    false, NULL),
    ('audio',     'audio',     false, NULL)
ON CONFLICT (id) DO NOTHING;
