-- backend/db/schema.sql
-- Canonical Postgres schema for agentic-rag.
-- Applied by the eval harness against a fresh `supabase start` instance.
--
-- To re-generate after prod schema changes:
--   1. supabase db dump --schema public --file backend/db/schema.sql
--   2. python3 backend/db/clean_schema.py
--
-- The cleaner strips owner / grant / revoke / default-privilege statements
-- and prepends the CREATE EXTENSION statements that pg_dump omits
-- (Supabase manages extensions separately from the public-schema dump).

CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

CREATE SCHEMA IF NOT EXISTS "public";

COMMENT ON SCHEMA "public" IS 'standard public schema';

CREATE OR REPLACE FUNCTION "public"."execute_readonly_query"("query_text" "text") RETURNS "jsonb"
    LANGUAGE "plpgsql" SECURITY DEFINER
    AS $$                                                                                                                                                                                   
  declare                                                                                                                                                                                 
    result jsonb;                                                                                                                                                                         
  begin                                                                                                                                                                                   
    if not (trim(upper(query_text)) like 'SELECT%') then                                                                                                                                
      raise exception 'Only SELECT queries are allowed';                                                                                                                                  
    end if;                                                                                                                                                                             
                                          
    if trim(upper(query_text)) ~ '\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)\b'                                                                                     
    then                                                                                                                                                                                  
      raise exception 'Query contains forbidden keywords';                                                                                                                                
    end if;                                                                                                                                                                               
                                                                                                                                                                                        
    execute format('select jsonb_agg(row_to_json(t)) from (%s) t', query_text) into result;                                                                                               
    return coalesce(result, '[]'::jsonb);                                                                                                                                                 
  end;                                                                                                                                                                                    
  $$;

CREATE OR REPLACE FUNCTION "public"."keyword_search"("search_query" "text", "match_count" integer DEFAULT 20, "filter_user_id" "uuid" DEFAULT NULL::"uuid", "filter_topic" "text" DEFAULT NULL::"text", "filter_keyword" "text" DEFAULT NULL::"text", "filter_root_folder_id" "uuid" DEFAULT NULL::"uuid") RETURNS TABLE("id" "uuid", "content" "text", "metadata" "jsonb", "rank" real)
    LANGUAGE "sql" STABLE
    AS $$
    SELECT id, content, metadata,
      ts_rank(fts, websearch_to_tsquery('english', search_query)) AS rank
    FROM documents
    WHERE fts @@ websearch_to_tsquery('english', search_query)
      AND (user_id = filter_user_id OR user_id IS NULL)
      AND (filter_topic IS NULL OR metadata->>'topic' = filter_topic)
      AND (filter_keyword IS NULL OR metadata->'keywords' ? filter_keyword)
      AND (filter_root_folder_id IS NULL OR root_folder_id = filter_root_folder_id)
    ORDER BY rank DESC
    LIMIT match_count;
  $$;

CREATE OR REPLACE FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer DEFAULT 5) RETURNS TABLE("id" "uuid", "content" "text", "metadata" "jsonb", "similarity" double precision)
    LANGUAGE "sql" STABLE
    AS $$
    select
      id,
      content,
      metadata,
      1 - (embedding <=> query_embedding) as similarity                                                                                                                                                          
    from documents
    order by embedding <=> query_embedding                                                                                                                                                                       
    limit match_count;                                                                                                                                                                                           
  $$;

CREATE OR REPLACE FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer DEFAULT 5, "filter_user_id" "uuid" DEFAULT NULL::"uuid", "filter_topic" "text" DEFAULT NULL::"text", "filter_keyword" "text" DEFAULT NULL::"text", "filter_root_folder_id" "uuid" DEFAULT NULL::"uuid") RETURNS TABLE("id" "uuid", "content" "text", "metadata" "jsonb", "similarity" double precision)
    LANGUAGE "sql" STABLE
    AS $$
    SELECT id, content, metadata,
      1 - (embedding <=> query_embedding) AS similarity
    FROM documents
    WHERE (user_id = filter_user_id OR user_id IS NULL)
      AND (filter_topic IS NULL OR metadata->>'topic' = filter_topic)
      AND (filter_keyword IS NULL OR metadata->'keywords' ? filter_keyword)
      AND (filter_root_folder_id IS NULL OR root_folder_id = filter_root_folder_id)
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
  $$;

CREATE OR REPLACE FUNCTION "public"."update_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$                                                                                                                                                                                          
  begin                                                                                                                                                                                                          
    new.updated_at = now();                                                                                                                                                                                    
    return new;                                                                                                                                                                                                  
  end;
  $$;

SET default_tablespace = '';

SET default_table_access_method = "heap";

CREATE TABLE IF NOT EXISTS "public"."api_keys" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "key_hash" "text" NOT NULL,
    "name" "text" DEFAULT 'Default'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "scope_folder_id" "uuid"
);

CREATE TABLE IF NOT EXISTS "public"."checkpoint_blobs" (
    "thread_id" "text" NOT NULL,
    "checkpoint_ns" "text" DEFAULT ''::"text" NOT NULL,
    "channel" "text" NOT NULL,
    "version" "text" NOT NULL,
    "type" "text" NOT NULL,
    "blob" "bytea"
);

CREATE TABLE IF NOT EXISTS "public"."checkpoint_migrations" (
    "v" integer NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."checkpoint_writes" (
    "thread_id" "text" NOT NULL,
    "checkpoint_ns" "text" DEFAULT ''::"text" NOT NULL,
    "checkpoint_id" "text" NOT NULL,
    "task_id" "text" NOT NULL,
    "idx" integer NOT NULL,
    "channel" "text" NOT NULL,
    "type" "text",
    "blob" "bytea" NOT NULL,
    "task_path" "text" DEFAULT ''::"text" NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."checkpoints" (
    "thread_id" "text" NOT NULL,
    "checkpoint_ns" "text" DEFAULT ''::"text" NOT NULL,
    "checkpoint_id" "text" NOT NULL,
    "parent_checkpoint_id" "text",
    "type" "text",
    "checkpoint" "jsonb" NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL
);

CREATE TABLE IF NOT EXISTS "public"."context" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "key" "text" NOT NULL,
    "value" "text" NOT NULL,
    "root_folder_id" "uuid",
    "user_id" "uuid" NOT NULL,
    "expires_at" timestamp with time zone DEFAULT ("now"() + '7 days'::interval) NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);

CREATE TABLE IF NOT EXISTS "public"."conversations" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "title" "text" DEFAULT 'New conversation'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);

CREATE TABLE IF NOT EXISTS "public"."documents" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "content" "text" NOT NULL,
    "embedding" "public"."vector"(1024),
    "metadata" "jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "user_id" "uuid",
    "source_filename" "text",
    "content_hash" "text",
    "status" "text" DEFAULT 'completed'::"text" NOT NULL,
    "source_type" "text",
    "folder_id" "uuid",
    "root_folder_id" "uuid",
    "notion_page_id" "text",
    "notion_last_edited_time" timestamp with time zone,
    "notion_parent_path" "text",
    "fts" "tsvector" GENERATED ALWAYS AS ("to_tsvector"('"english"'::"regconfig", "content")) STORED,
    CONSTRAINT "documents_status_check" CHECK (("status" = ANY (ARRAY['processing'::"text", 'completed'::"text", 'failed'::"text"])))
);

CREATE TABLE IF NOT EXISTS "public"."folders" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "parent_id" "uuid",
    "user_id" "uuid" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"()
);

CREATE TABLE IF NOT EXISTS "public"."notion_sync_configs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "root_folder_id" "uuid" NOT NULL,
    "notion_page_id" "text" NOT NULL,
    "notion_page_title" "text",
    "integration_token_encrypted" "text" NOT NULL,
    "fast_poll_interval_min" integer DEFAULT 5 NOT NULL,
    "full_reconciliation_interval_hours" integer DEFAULT 24 NOT NULL,
    "last_fast_sync_at" timestamp with time zone,
    "last_full_sync_at" timestamp with time zone,
    "last_error" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);

CREATE TABLE IF NOT EXISTS "public"."ingestion_status" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "text" NOT NULL,
    "filename" "text" NOT NULL,
    "folder_id" "uuid",
    "stage" "text" DEFAULT 'uploading'::"text" NOT NULL,
    "stage_detail" "text",
    "error_message" "text",
    "chunks_total" integer,
    "chunks_done" integer DEFAULT 0,
    "duplicate" boolean DEFAULT false,
    "document_ids" "jsonb" DEFAULT '[]'::"jsonb",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "ingestion_status_stage_check" CHECK (("stage" = ANY (ARRAY['uploading'::"text", 'parsing'::"text", 'chunking'::"text", 'extracting_metadata'::"text", 'embedding'::"text", 'storing'::"text", 'completed'::"text", 'error'::"text", 'duplicate'::"text"])))
);

CREATE TABLE IF NOT EXISTS "public"."messages" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "role" "text" NOT NULL,
    "content" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "messages_role_check" CHECK (("role" = ANY (ARRAY['user'::"text", 'assistant'::"text"])))
);

CREATE TABLE IF NOT EXISTS "public"."notes" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "title" "text" NOT NULL,
    "content" "text" NOT NULL,
    "content_hash" "text" NOT NULL,
    "root_folder_id" "uuid",
    "user_id" "uuid" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);

ALTER TABLE ONLY "public"."api_keys"
    ADD CONSTRAINT "api_keys_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."api_keys"
    ADD CONSTRAINT "api_keys_user_scope_unique" UNIQUE ("user_id", "scope_folder_id");

ALTER TABLE ONLY "public"."checkpoint_blobs"
    ADD CONSTRAINT "checkpoint_blobs_pkey" PRIMARY KEY ("thread_id", "checkpoint_ns", "channel", "version");

ALTER TABLE ONLY "public"."checkpoint_migrations"
    ADD CONSTRAINT "checkpoint_migrations_pkey" PRIMARY KEY ("v");

ALTER TABLE ONLY "public"."checkpoint_writes"
    ADD CONSTRAINT "checkpoint_writes_pkey" PRIMARY KEY ("thread_id", "checkpoint_ns", "checkpoint_id", "task_id", "idx");

ALTER TABLE ONLY "public"."checkpoints"
    ADD CONSTRAINT "checkpoints_pkey" PRIMARY KEY ("thread_id", "checkpoint_ns", "checkpoint_id");

ALTER TABLE ONLY "public"."context"
    ADD CONSTRAINT "context_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."context"
    ADD CONSTRAINT "context_user_scope_key_unique" UNIQUE ("user_id", "root_folder_id", "key");

ALTER TABLE ONLY "public"."conversations"
    ADD CONSTRAINT "conversations_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."folders"
    ADD CONSTRAINT "folders_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."ingestion_status"
    ADD CONSTRAINT "ingestion_status_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."notes"
    ADD CONSTRAINT "notes_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."notion_sync_configs"
    ADD CONSTRAINT "notion_sync_configs_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."notion_sync_configs"
    ADD CONSTRAINT "notion_sync_configs_user_page_unique" UNIQUE ("user_id", "notion_page_id");

CREATE INDEX "api_keys_key_hash_idx" ON "public"."api_keys" USING "btree" ("key_hash");

CREATE INDEX "checkpoint_blobs_thread_id_idx" ON "public"."checkpoint_blobs" USING "btree" ("thread_id");

CREATE INDEX "checkpoint_writes_thread_id_idx" ON "public"."checkpoint_writes" USING "btree" ("thread_id");

CREATE INDEX "checkpoints_thread_id_idx" ON "public"."checkpoints" USING "btree" ("thread_id");

CREATE INDEX "documents_embedding_idx" ON "public"."documents" USING "hnsw" ("embedding" "public"."vector_cosine_ops");

CREATE INDEX "documents_fts_idx" ON "public"."documents" USING "gin" ("fts");

CREATE INDEX "idx_context_expires" ON "public"."context" USING "btree" ("expires_at");

CREATE INDEX "idx_documents_root_folder_id" ON "public"."documents" USING "btree" ("root_folder_id");

CREATE INDEX "idx_documents_notion_page_id" ON "public"."documents" USING "btree" ("notion_page_id") WHERE ("notion_page_id" IS NOT NULL);

CREATE UNIQUE INDEX "idx_documents_notion_identity" ON "public"."documents" USING "btree" ("user_id", "root_folder_id", "notion_page_id", "content") WHERE ("notion_page_id" IS NOT NULL);

CREATE UNIQUE INDEX "idx_notes_dedup" ON "public"."notes" USING "btree" ("user_id", "root_folder_id", "content_hash");

CREATE INDEX "idx_notes_user_scope" ON "public"."notes" USING "btree" ("user_id", "root_folder_id");

CREATE INDEX "idx_notion_sync_configs_user_id" ON "public"."notion_sync_configs" USING "btree" ("user_id");

CREATE OR REPLACE TRIGGER "context_updated_at" BEFORE UPDATE ON "public"."context" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();

CREATE OR REPLACE TRIGGER "conversations_updated_at" BEFORE UPDATE ON "public"."conversations" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();

CREATE OR REPLACE TRIGGER "ingestion_status_updated_at" BEFORE UPDATE ON "public"."ingestion_status" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();

CREATE OR REPLACE TRIGGER "notes_updated_at" BEFORE UPDATE ON "public"."notes" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();

CREATE OR REPLACE TRIGGER "notion_sync_configs_updated_at" BEFORE UPDATE ON "public"."notion_sync_configs" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();

ALTER TABLE ONLY "public"."api_keys"
    ADD CONSTRAINT "api_keys_scope_folder_id_fkey" FOREIGN KEY ("scope_folder_id") REFERENCES "public"."folders"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."api_keys"
    ADD CONSTRAINT "api_keys_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."context"
    ADD CONSTRAINT "context_root_folder_id_fkey" FOREIGN KEY ("root_folder_id") REFERENCES "public"."folders"("id") ON DELETE SET NULL;

ALTER TABLE ONLY "public"."context"
    ADD CONSTRAINT "context_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."conversations"
    ADD CONSTRAINT "conversations_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_folder_id_fkey" FOREIGN KEY ("folder_id") REFERENCES "public"."folders"("id") ON DELETE SET NULL;

ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_root_folder_id_fkey" FOREIGN KEY ("root_folder_id") REFERENCES "public"."folders"("id") ON DELETE SET NULL;

ALTER TABLE ONLY "public"."documents"
    ADD CONSTRAINT "documents_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."folders"
    ADD CONSTRAINT "folders_parent_id_fkey" FOREIGN KEY ("parent_id") REFERENCES "public"."folders"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."folders"
    ADD CONSTRAINT "folders_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."ingestion_status"
    ADD CONSTRAINT "ingestion_status_folder_id_fkey" FOREIGN KEY ("folder_id") REFERENCES "public"."folders"("id") ON DELETE SET NULL;

ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."notes"
    ADD CONSTRAINT "notes_root_folder_id_fkey" FOREIGN KEY ("root_folder_id") REFERENCES "public"."folders"("id") ON DELETE SET NULL;

ALTER TABLE ONLY "public"."notes"
    ADD CONSTRAINT "notes_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."notion_sync_configs"
    ADD CONSTRAINT "notion_sync_configs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;

ALTER TABLE ONLY "public"."notion_sync_configs"
    ADD CONSTRAINT "notion_sync_configs_root_folder_id_fkey" FOREIGN KEY ("root_folder_id") REFERENCES "public"."folders"("id") ON DELETE CASCADE;

CREATE POLICY "Users manage own api keys" ON "public"."api_keys" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));

CREATE POLICY "Users manage own context" ON "public"."context" USING (("user_id" = "auth"."uid"())) WITH CHECK (("user_id" = "auth"."uid"()));

CREATE POLICY "Users manage own conversations" ON "public"."conversations" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));

CREATE POLICY "Users manage own documents" ON "public"."documents" USING ((("user_id" = "auth"."uid"()) OR ("user_id" IS NULL))) WITH CHECK (("user_id" = "auth"."uid"()));

CREATE POLICY "Users manage own folders" ON "public"."folders" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));

CREATE POLICY "Users manage own messages" ON "public"."messages" USING (("conversation_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = "auth"."uid"())))) WITH CHECK (("conversation_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = "auth"."uid"()))));

CREATE POLICY "Users manage own notes" ON "public"."notes" USING (("user_id" = "auth"."uid"())) WITH CHECK (("user_id" = "auth"."uid"()));

CREATE POLICY "Users manage own notion sync configs" ON "public"."notion_sync_configs" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));

CREATE POLICY "Users see own ingestion status" ON "public"."ingestion_status" USING (("user_id" = ("auth"."uid"())::"text")) WITH CHECK (("user_id" = ("auth"."uid"())::"text"));

ALTER TABLE "public"."api_keys" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."context" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."conversations" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."documents" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."folders" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."ingestion_status" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."messages" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."notes" ENABLE ROW LEVEL SECURITY;

ALTER TABLE "public"."notion_sync_configs" ENABLE ROW LEVEL SECURITY;


