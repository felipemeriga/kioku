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

-- Eval user — documents.user_id has an FK to auth.users(id). The runner uses
-- this synthetic UUID (EVAL_USER_ID in backend/eval/runner.py); satisfy the
-- FK so ingestion inserts can land. Local-only; never insert into prod
-- auth.users from SQL.
INSERT INTO auth.users (
    id, instance_id, email, aud, role,
    email_confirmed_at, created_at, updated_at,
    raw_app_meta_data, raw_user_meta_data
)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000000',
    'eval@local.test',
    'authenticated',
    'authenticated',
    now(), now(), now(),
    '{}'::jsonb, '{}'::jsonb
)
ON CONFLICT (id) DO NOTHING;
