-- Disposable isolated PostgreSQL database only. Minimal production table shapes.
CREATE SCHEMA auth;
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'SELECT NULL::uuid';
CREATE TABLE auth.users(id uuid PRIMARY KEY);
CREATE TABLE public.folders(id uuid PRIMARY KEY,user_id uuid NOT NULL,kind text NOT NULL);
CREATE TABLE public.folder_summaries(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),folder_id uuid,user_id uuid,kind text,trigger text,content jsonb,sections jsonb,briefing_schema_version integer,generated_at timestamptz DEFAULT clock_timestamp());
CREATE TABLE public.repo_documentation(id uuid PRIMARY KEY DEFAULT gen_random_uuid(),folder_id uuid,user_id uuid,content text,abstract text,generated_at timestamptz DEFAULT clock_timestamp());
CREATE TABLE public.repo_freshness(folder_id uuid PRIMARY KEY,user_id uuid,section_reviews jsonb DEFAULT '{}');
