BEGIN;
CREATE SCHEMA auth;
CREATE TABLE auth.users(id uuid PRIMARY KEY);
CREATE TABLE public.conversations(id uuid PRIMARY KEY,user_id uuid NOT NULL,title text);
CREATE TABLE public.messages(id uuid PRIMARY KEY,conversation_id uuid,role text,content text,debug jsonb,citations jsonb);
CREATE TABLE public.folders(id uuid PRIMARY KEY,user_id uuid,parent_id uuid,name text);
CREATE TABLE public.documents(id uuid PRIMARY KEY,user_id uuid,folder_id uuid,source_filename text,source_type text,created_at timestamptz);
DO $$ BEGIN
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon; END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated; END IF;
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role; END IF;
END $$;
INSERT INTO auth.users VALUES('11111111-1111-1111-1111-111111111111'),('22222222-2222-2222-2222-222222222222');
INSERT INTO conversations VALUES('33333333-3333-3333-3333-333333333333','11111111-1111-1111-1111-111111111111','New conversation');
INSERT INTO folders VALUES('44444444-4444-4444-4444-444444444444','11111111-1111-1111-1111-111111111111',NULL,'repo');
