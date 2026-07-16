


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


ALTER SCHEMA "public" OWNER TO "pg_database_owner";


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


ALTER FUNCTION "public"."execute_readonly_query"("query_text" "text") OWNER TO "postgres";


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


ALTER FUNCTION "public"."keyword_search"("search_query" "text", "match_count" integer, "filter_user_id" "uuid", "filter_topic" "text", "filter_keyword" "text", "filter_root_folder_id" "uuid") OWNER TO "postgres";


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


ALTER FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer) OWNER TO "postgres";


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


ALTER FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer, "filter_user_id" "uuid", "filter_topic" "text", "filter_keyword" "text", "filter_root_folder_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."update_updated_at"() RETURNS "trigger"
    LANGUAGE "plpgsql"
    AS $$                                                                                                                                                                                          
  begin                                                                                                                                                                                                          
    new.updated_at = now();                                                                                                                                                                                    
    return new;                                                                                                                                                                                                  
  end;
  $$;


ALTER FUNCTION "public"."update_updated_at"() OWNER TO "postgres";

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


ALTER TABLE "public"."api_keys" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."checkpoint_blobs" (
    "thread_id" "text" NOT NULL,
    "checkpoint_ns" "text" DEFAULT ''::"text" NOT NULL,
    "channel" "text" NOT NULL,
    "version" "text" NOT NULL,
    "type" "text" NOT NULL,
    "blob" "bytea"
);


ALTER TABLE "public"."checkpoint_blobs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."checkpoint_migrations" (
    "v" integer NOT NULL
);


ALTER TABLE "public"."checkpoint_migrations" OWNER TO "postgres";


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


ALTER TABLE "public"."checkpoint_writes" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."checkpoints" (
    "thread_id" "text" NOT NULL,
    "checkpoint_ns" "text" DEFAULT ''::"text" NOT NULL,
    "checkpoint_id" "text" NOT NULL,
    "parent_checkpoint_id" "text",
    "type" "text",
    "checkpoint" "jsonb" NOT NULL,
    "metadata" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL
);


ALTER TABLE "public"."checkpoints" OWNER TO "postgres";


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


ALTER TABLE "public"."context" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."conversations" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "title" "text" DEFAULT 'New conversation'::"text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."conversations" OWNER TO "postgres";


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
    "fts" "tsvector" GENERATED ALWAYS AS ("to_tsvector"('"english"'::"regconfig", "content")) STORED,
    "folder_id" "uuid",
    "root_folder_id" "uuid",
    "notion_page_id" "text",
    "notion_last_edited_time" timestamp with time zone,
    "notion_parent_path" "text",
    "chunk_index" integer,
    CONSTRAINT "documents_status_check" CHECK (("status" = ANY (ARRAY['processing'::"text", 'completed'::"text", 'failed'::"text", 'deleted'::"text"])))
);


ALTER TABLE "public"."documents" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."folder_summaries" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "folder_id" "uuid" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "generated_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "kind" "text" NOT NULL,
    "content" "jsonb" NOT NULL,
    "previous_content" "jsonb",
    "included_hashes" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "doc_count" integer DEFAULT 0 NOT NULL,
    "changed_files" "jsonb" DEFAULT '{}'::"jsonb" NOT NULL,
    "input_tokens" integer,
    "output_tokens" integer,
    "duration_ms" integer,
    "trigger" "text",
    CONSTRAINT "folder_summaries_kind_check" CHECK (("kind" = ANY (ARRAY['full'::"text", 'delta'::"text", 'seed'::"text"]))),
    CONSTRAINT "folder_summaries_trigger_check" CHECK ((("trigger" IS NULL) OR ("trigger" = ANY (ARRAY['cron_nightly'::"text", 'cron_weekly'::"text", 'manual'::"text", 'seed'::"text"]))))
);


ALTER TABLE "public"."folder_summaries" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."folders" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "parent_id" "uuid",
    "user_id" "uuid" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."folders" OWNER TO "postgres";



CREATE TABLE IF NOT EXISTS "public"."ingestion_jobs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "kind" "text" NOT NULL,
    "source_ref" "text" NOT NULL,
    "parent_job_id" "uuid",
    "root_folder_id" "uuid",
    "status" "text" DEFAULT 'queued'::"text" NOT NULL,
    "current_step" "text",
    "total_batches" integer DEFAULT 0 NOT NULL,
    "processed_batches" integer DEFAULT 0 NOT NULL,
    "total_pages" integer,
    "processed_pages" integer,
    "error" "text",
    "started_at" timestamp with time zone,
    "completed_at" timestamp with time zone,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "ingestion_jobs_kind_check" CHECK (("kind" = ANY (ARRAY['upload'::"text", 'drop'::"text", 'notion_sync'::"text", 'notion_page'::"text"]))),
    CONSTRAINT "ingestion_jobs_status_check" CHECK (("status" = ANY (ARRAY['queued'::"text", 'running'::"text", 'completed'::"text", 'failed'::"text"])))
);


ALTER TABLE "public"."ingestion_jobs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."mem0_sync_configs" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "root_folder_id" "uuid" NOT NULL,
    "api_key_encrypted" "text" NOT NULL,
    "org_id" "text",
    "project_id" "text",
    "last_verified_at" timestamp with time zone,
    "last_error" "text",
    "created_at" timestamp with time zone DEFAULT "now"(),
    "updated_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."mem0_sync_configs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."messages" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "role" "text" NOT NULL,
    "content" "text" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "messages_role_check" CHECK (("role" = ANY (ARRAY['user'::"text", 'assistant'::"text"])))
);


ALTER TABLE "public"."messages" OWNER TO "postgres";


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


ALTER TABLE "public"."notes" OWNER TO "postgres";


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


ALTER TABLE "public"."notion_sync_configs" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."retrieval_log" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "folder_id" "uuid",
    "query" "text" NOT NULL,
    "sources_hit" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "chunks_returned" integer DEFAULT 0 NOT NULL,
    "chunk_ids" "jsonb" DEFAULT '[]'::"jsonb" NOT NULL,
    "latency_ms" integer,
    "channel" "text",
    "conversation_id" "uuid",
    "created_at" timestamp with time zone DEFAULT "now"()
);


ALTER TABLE "public"."retrieval_log" OWNER TO "postgres";


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



ALTER TABLE ONLY "public"."folder_summaries"
    ADD CONSTRAINT "folder_summaries_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."folders"
    ADD CONSTRAINT "folders_pkey" PRIMARY KEY ("id");




ALTER TABLE ONLY "public"."ingestion_jobs"
    ADD CONSTRAINT "ingestion_jobs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."mem0_sync_configs"
    ADD CONSTRAINT "mem0_sync_configs_folder_unique" UNIQUE ("user_id", "root_folder_id");



ALTER TABLE ONLY "public"."mem0_sync_configs"
    ADD CONSTRAINT "mem0_sync_configs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."notes"
    ADD CONSTRAINT "notes_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."notion_sync_configs"
    ADD CONSTRAINT "notion_sync_configs_pkey" PRIMARY KEY ("id");



ALTER TABLE ONLY "public"."notion_sync_configs"
    ADD CONSTRAINT "notion_sync_configs_user_page_unique" UNIQUE ("user_id", "notion_page_id");



ALTER TABLE ONLY "public"."retrieval_log"
    ADD CONSTRAINT "retrieval_log_pkey" PRIMARY KEY ("id");



CREATE INDEX "api_keys_key_hash_idx" ON "public"."api_keys" USING "btree" ("key_hash");



CREATE INDEX "checkpoint_blobs_thread_id_idx" ON "public"."checkpoint_blobs" USING "btree" ("thread_id");



CREATE INDEX "checkpoint_writes_thread_id_idx" ON "public"."checkpoint_writes" USING "btree" ("thread_id");



CREATE INDEX "checkpoints_thread_id_idx" ON "public"."checkpoints" USING "btree" ("thread_id");



CREATE INDEX "documents_embedding_idx" ON "public"."documents" USING "hnsw" ("embedding" "public"."vector_cosine_ops");



CREATE INDEX "documents_fts_idx" ON "public"."documents" USING "gin" ("fts");



CREATE INDEX "folder_summaries_folder_id_generated_at_idx" ON "public"."folder_summaries" USING "btree" ("folder_id", "generated_at" DESC);



CREATE INDEX "folder_summaries_user_id_idx" ON "public"."folder_summaries" USING "btree" ("user_id");



CREATE INDEX "idx_context_expires" ON "public"."context" USING "btree" ("expires_at");



CREATE UNIQUE INDEX "idx_documents_ingest_chunk_identity" ON "public"."documents" USING "btree" ("user_id", "source_filename", "chunk_index") WHERE (("chunk_index" IS NOT NULL) AND ("notion_page_id" IS NULL));



CREATE UNIQUE INDEX "idx_documents_notion_identity" ON "public"."documents" USING "btree" ("user_id", "root_folder_id", "notion_page_id", "content") WHERE ("notion_page_id" IS NOT NULL);



CREATE INDEX "idx_documents_notion_page_id" ON "public"."documents" USING "btree" ("notion_page_id") WHERE ("notion_page_id" IS NOT NULL);



CREATE INDEX "idx_documents_root_folder_id" ON "public"."documents" USING "btree" ("root_folder_id");




CREATE UNIQUE INDEX "idx_ingestion_jobs_active_source" ON "public"."ingestion_jobs" USING "btree" ("kind", "source_ref") WHERE ("status" = ANY (ARRAY['queued'::"text", 'running'::"text"]));



CREATE INDEX "idx_ingestion_jobs_user_status" ON "public"."ingestion_jobs" USING "btree" ("user_id", "status");



CREATE INDEX "idx_mem0_sync_configs_user_id" ON "public"."mem0_sync_configs" USING "btree" ("user_id");



CREATE UNIQUE INDEX "idx_notes_dedup" ON "public"."notes" USING "btree" ("user_id", "root_folder_id", "content_hash");



CREATE INDEX "idx_notes_user_scope" ON "public"."notes" USING "btree" ("user_id", "root_folder_id");



CREATE INDEX "idx_notion_sync_configs_user_id" ON "public"."notion_sync_configs" USING "btree" ("user_id");



CREATE INDEX "idx_retrieval_log_folder_id" ON "public"."retrieval_log" USING "btree" ("folder_id") WHERE ("folder_id" IS NOT NULL);



CREATE INDEX "idx_retrieval_log_user_id_created_at" ON "public"."retrieval_log" USING "btree" ("user_id", "created_at" DESC);



CREATE OR REPLACE TRIGGER "context_updated_at" BEFORE UPDATE ON "public"."context" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();



CREATE OR REPLACE TRIGGER "conversations_updated_at" BEFORE UPDATE ON "public"."conversations" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();




CREATE OR REPLACE TRIGGER "ingestion_jobs_updated_at" BEFORE UPDATE ON "public"."ingestion_jobs" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();



CREATE OR REPLACE TRIGGER "mem0_sync_configs_updated_at" BEFORE UPDATE ON "public"."mem0_sync_configs" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();



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



ALTER TABLE ONLY "public"."folder_summaries"
    ADD CONSTRAINT "folder_summaries_folder_id_fkey" FOREIGN KEY ("folder_id") REFERENCES "public"."folders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."folder_summaries"
    ADD CONSTRAINT "folder_summaries_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."folders"
    ADD CONSTRAINT "folders_parent_id_fkey" FOREIGN KEY ("parent_id") REFERENCES "public"."folders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."folders"
    ADD CONSTRAINT "folders_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;




ALTER TABLE ONLY "public"."ingestion_jobs"
    ADD CONSTRAINT "ingestion_jobs_parent_job_id_fkey" FOREIGN KEY ("parent_job_id") REFERENCES "public"."ingestion_jobs"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."ingestion_jobs"
    ADD CONSTRAINT "ingestion_jobs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."mem0_sync_configs"
    ADD CONSTRAINT "mem0_sync_configs_folder_fk" FOREIGN KEY ("root_folder_id") REFERENCES "public"."folders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."mem0_sync_configs"
    ADD CONSTRAINT "mem0_sync_configs_user_fk" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."messages"
    ADD CONSTRAINT "messages_conversation_id_fkey" FOREIGN KEY ("conversation_id") REFERENCES "public"."conversations"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."notes"
    ADD CONSTRAINT "notes_root_folder_id_fkey" FOREIGN KEY ("root_folder_id") REFERENCES "public"."folders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."notes"
    ADD CONSTRAINT "notes_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."notion_sync_configs"
    ADD CONSTRAINT "notion_sync_configs_root_folder_id_fkey" FOREIGN KEY ("root_folder_id") REFERENCES "public"."folders"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."notion_sync_configs"
    ADD CONSTRAINT "notion_sync_configs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



ALTER TABLE ONLY "public"."retrieval_log"
    ADD CONSTRAINT "retrieval_log_folder_fk" FOREIGN KEY ("folder_id") REFERENCES "public"."folders"("id") ON DELETE SET NULL;



ALTER TABLE ONLY "public"."retrieval_log"
    ADD CONSTRAINT "retrieval_log_user_fk" FOREIGN KEY ("user_id") REFERENCES "auth"."users"("id") ON DELETE CASCADE;



CREATE POLICY "Users insert own retrieval log" ON "public"."retrieval_log" FOR INSERT WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "Users manage own api keys" ON "public"."api_keys" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "Users manage own context" ON "public"."context" USING (("user_id" = "auth"."uid"())) WITH CHECK (("user_id" = "auth"."uid"()));



CREATE POLICY "Users manage own conversations" ON "public"."conversations" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "Users manage own documents" ON "public"."documents" USING ((("user_id" = "auth"."uid"()) OR ("user_id" IS NULL))) WITH CHECK (("user_id" = "auth"."uid"()));



CREATE POLICY "Users manage own folder summaries" ON "public"."folder_summaries" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "Users manage own folders" ON "public"."folders" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));




CREATE POLICY "Users manage own ingestion jobs" ON "public"."ingestion_jobs" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "Users manage own mem0 configs" ON "public"."mem0_sync_configs" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "Users manage own messages" ON "public"."messages" USING (("conversation_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = "auth"."uid"())))) WITH CHECK (("conversation_id" IN ( SELECT "conversations"."id"
   FROM "public"."conversations"
  WHERE ("conversations"."user_id" = "auth"."uid"()))));



CREATE POLICY "Users manage own notes" ON "public"."notes" USING (("user_id" = "auth"."uid"())) WITH CHECK (("user_id" = "auth"."uid"()));



CREATE POLICY "Users manage own notion sync configs" ON "public"."notion_sync_configs" USING (("auth"."uid"() = "user_id")) WITH CHECK (("auth"."uid"() = "user_id"));



CREATE POLICY "Users read own retrieval log" ON "public"."retrieval_log" FOR SELECT USING (("auth"."uid"() = "user_id"));



ALTER TABLE "public"."api_keys" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."context" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."conversations" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."documents" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."folder_summaries" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."folders" ENABLE ROW LEVEL SECURITY;



ALTER TABLE "public"."ingestion_jobs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."mem0_sync_configs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."messages" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."notes" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."notion_sync_configs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."retrieval_log" ENABLE ROW LEVEL SECURITY;


GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";



GRANT ALL ON FUNCTION "public"."execute_readonly_query"("query_text" "text") TO "anon";
GRANT ALL ON FUNCTION "public"."execute_readonly_query"("query_text" "text") TO "authenticated";
GRANT ALL ON FUNCTION "public"."execute_readonly_query"("query_text" "text") TO "service_role";



GRANT ALL ON FUNCTION "public"."keyword_search"("search_query" "text", "match_count" integer, "filter_user_id" "uuid", "filter_topic" "text", "filter_keyword" "text", "filter_root_folder_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."keyword_search"("search_query" "text", "match_count" integer, "filter_user_id" "uuid", "filter_topic" "text", "filter_keyword" "text", "filter_root_folder_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."keyword_search"("search_query" "text", "match_count" integer, "filter_user_id" "uuid", "filter_topic" "text", "filter_keyword" "text", "filter_root_folder_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer) TO "anon";
GRANT ALL ON FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer) TO "authenticated";
GRANT ALL ON FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer) TO "service_role";



GRANT ALL ON FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer, "filter_user_id" "uuid", "filter_topic" "text", "filter_keyword" "text", "filter_root_folder_id" "uuid") TO "anon";
GRANT ALL ON FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer, "filter_user_id" "uuid", "filter_topic" "text", "filter_keyword" "text", "filter_root_folder_id" "uuid") TO "authenticated";
GRANT ALL ON FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer, "filter_user_id" "uuid", "filter_topic" "text", "filter_keyword" "text", "filter_root_folder_id" "uuid") TO "service_role";



GRANT ALL ON FUNCTION "public"."update_updated_at"() TO "anon";
GRANT ALL ON FUNCTION "public"."update_updated_at"() TO "authenticated";
GRANT ALL ON FUNCTION "public"."update_updated_at"() TO "service_role";



GRANT ALL ON TABLE "public"."api_keys" TO "anon";
GRANT ALL ON TABLE "public"."api_keys" TO "authenticated";
GRANT ALL ON TABLE "public"."api_keys" TO "service_role";



GRANT ALL ON TABLE "public"."checkpoint_blobs" TO "anon";
GRANT ALL ON TABLE "public"."checkpoint_blobs" TO "authenticated";
GRANT ALL ON TABLE "public"."checkpoint_blobs" TO "service_role";



GRANT ALL ON TABLE "public"."checkpoint_migrations" TO "anon";
GRANT ALL ON TABLE "public"."checkpoint_migrations" TO "authenticated";
GRANT ALL ON TABLE "public"."checkpoint_migrations" TO "service_role";



GRANT ALL ON TABLE "public"."checkpoint_writes" TO "anon";
GRANT ALL ON TABLE "public"."checkpoint_writes" TO "authenticated";
GRANT ALL ON TABLE "public"."checkpoint_writes" TO "service_role";



GRANT ALL ON TABLE "public"."checkpoints" TO "anon";
GRANT ALL ON TABLE "public"."checkpoints" TO "authenticated";
GRANT ALL ON TABLE "public"."checkpoints" TO "service_role";



GRANT ALL ON TABLE "public"."context" TO "anon";
GRANT ALL ON TABLE "public"."context" TO "authenticated";
GRANT ALL ON TABLE "public"."context" TO "service_role";



GRANT ALL ON TABLE "public"."conversations" TO "anon";
GRANT ALL ON TABLE "public"."conversations" TO "authenticated";
GRANT ALL ON TABLE "public"."conversations" TO "service_role";



GRANT ALL ON TABLE "public"."documents" TO "anon";
GRANT ALL ON TABLE "public"."documents" TO "authenticated";
GRANT ALL ON TABLE "public"."documents" TO "service_role";



GRANT ALL ON TABLE "public"."folder_summaries" TO "anon";
GRANT ALL ON TABLE "public"."folder_summaries" TO "authenticated";
GRANT ALL ON TABLE "public"."folder_summaries" TO "service_role";



GRANT ALL ON TABLE "public"."folders" TO "anon";
GRANT ALL ON TABLE "public"."folders" TO "authenticated";
GRANT ALL ON TABLE "public"."folders" TO "service_role";




GRANT ALL ON TABLE "public"."ingestion_jobs" TO "anon";
GRANT ALL ON TABLE "public"."ingestion_jobs" TO "authenticated";
GRANT ALL ON TABLE "public"."ingestion_jobs" TO "service_role";



GRANT ALL ON TABLE "public"."mem0_sync_configs" TO "anon";
GRANT ALL ON TABLE "public"."mem0_sync_configs" TO "authenticated";
GRANT ALL ON TABLE "public"."mem0_sync_configs" TO "service_role";



GRANT ALL ON TABLE "public"."messages" TO "anon";
GRANT ALL ON TABLE "public"."messages" TO "authenticated";
GRANT ALL ON TABLE "public"."messages" TO "service_role";



GRANT ALL ON TABLE "public"."notes" TO "anon";
GRANT ALL ON TABLE "public"."notes" TO "authenticated";
GRANT ALL ON TABLE "public"."notes" TO "service_role";



GRANT ALL ON TABLE "public"."notion_sync_configs" TO "anon";
GRANT ALL ON TABLE "public"."notion_sync_configs" TO "authenticated";
GRANT ALL ON TABLE "public"."notion_sync_configs" TO "service_role";



GRANT ALL ON TABLE "public"."retrieval_log" TO "anon";
GRANT ALL ON TABLE "public"."retrieval_log" TO "authenticated";
GRANT ALL ON TABLE "public"."retrieval_log" TO "service_role";



ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON FUNCTIONS TO "service_role";






ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "postgres";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "postgres" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";







