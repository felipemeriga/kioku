


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

-- SECURITY DEFINER + arbitrary SELECT: must only be callable by the backend
-- (service_role), never via the public anon key. Drop the implicit PUBLIC grant.
REVOKE ALL ON FUNCTION "public"."execute_readonly_query"("query_text" "text") FROM PUBLIC;


CREATE OR REPLACE FUNCTION "public"."keyword_search"("search_query" "text", "match_count" integer DEFAULT 20, "filter_user_id" "uuid" DEFAULT NULL::"uuid", "filter_topic" "text" DEFAULT NULL::"text", "filter_keyword" "text" DEFAULT NULL::"text", "filter_root_folder_id" "uuid" DEFAULT NULL::"uuid", "filter_folder_ids" "uuid"[] DEFAULT NULL::"uuid"[], "filter_source_filename" "text" DEFAULT NULL::"text", "filter_created_after" timestamp with time zone DEFAULT NULL, "filter_created_before" timestamp with time zone DEFAULT NULL) RETURNS TABLE("id" "uuid", "content" "text", "metadata" "jsonb", "rank" real, "created_at" timestamp with time zone, "source_type" "text", "last_updated" timestamp with time zone)
    LANGUAGE "sql" STABLE
    AS $$
    SELECT id, content, metadata,
      ts_rank(fts, websearch_to_tsquery('english', search_query)) AS rank,
      created_at, source_type, last_updated
    FROM documents
    WHERE fts @@ websearch_to_tsquery('english', search_query)
      AND (user_id = filter_user_id OR user_id IS NULL)
      AND (filter_topic IS NULL OR metadata->>'topic' = filter_topic)
      AND (filter_keyword IS NULL OR metadata->'keywords' ? filter_keyword)
      AND (filter_root_folder_id IS NULL OR root_folder_id = filter_root_folder_id)
      AND (filter_folder_ids IS NULL OR folder_id = ANY(filter_folder_ids))
      AND (filter_source_filename IS NULL OR source_filename = filter_source_filename)
      AND (filter_created_after IS NULL OR created_at >= filter_created_after)
      AND (filter_created_before IS NULL OR created_at <= filter_created_before)
    ORDER BY rank DESC
    LIMIT match_count;
  $$;


ALTER FUNCTION "public"."keyword_search"("search_query" "text", "match_count" integer, "filter_user_id" "uuid", "filter_topic" "text", "filter_keyword" "text", "filter_root_folder_id" "uuid", "filter_folder_ids" "uuid"[], "filter_source_filename" "text", "filter_created_after" timestamp with time zone, "filter_created_before" timestamp with time zone) OWNER TO "postgres";


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


CREATE OR REPLACE FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer DEFAULT 5, "filter_user_id" "uuid" DEFAULT NULL::"uuid", "filter_topic" "text" DEFAULT NULL::"text", "filter_keyword" "text" DEFAULT NULL::"text", "filter_root_folder_id" "uuid" DEFAULT NULL::"uuid", "filter_folder_ids" "uuid"[] DEFAULT NULL::"uuid"[], "filter_source_filename" "text" DEFAULT NULL::"text", "filter_created_after" timestamp with time zone DEFAULT NULL, "filter_created_before" timestamp with time zone DEFAULT NULL) RETURNS TABLE("id" "uuid", "content" "text", "metadata" "jsonb", "similarity" double precision, "created_at" timestamp with time zone, "source_type" "text", "last_updated" timestamp with time zone)
    LANGUAGE "sql" STABLE
    AS $$
    SELECT id, content, metadata,
      1 - (embedding <=> query_embedding) AS similarity,
      created_at, source_type, last_updated
    FROM documents
    WHERE (user_id = filter_user_id OR user_id IS NULL)
      AND (filter_topic IS NULL OR metadata->>'topic' = filter_topic)
      AND (filter_keyword IS NULL OR metadata->'keywords' ? filter_keyword)
      AND (filter_root_folder_id IS NULL OR root_folder_id = filter_root_folder_id)
      AND (filter_folder_ids IS NULL OR folder_id = ANY(filter_folder_ids))
      AND (filter_source_filename IS NULL OR source_filename = filter_source_filename)
      AND (filter_created_after IS NULL OR created_at >= filter_created_after)
      AND (filter_created_before IS NULL OR created_at <= filter_created_before)
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
  $$;


ALTER FUNCTION "public"."match_documents"("query_embedding" "public"."vector", "match_count" integer, "filter_user_id" "uuid", "filter_topic" "text", "filter_keyword" "text", "filter_root_folder_id" "uuid", "filter_folder_ids" "uuid"[], "filter_source_filename" "text", "filter_created_after" timestamp with time zone, "filter_created_before" timestamp with time zone) OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."list_documents_grouped"(
    "p_user_id" "uuid",
    "p_folder_id" "uuid" DEFAULT NULL
) RETURNS TABLE(
    "source_filename" "text",
    "source_type" "text",
    "has_file" boolean,
    "chunks" bigint,
    "status" "text",
    "created_at" timestamp with time zone,
    "folder_id" "uuid"
)
    LANGUAGE "sql" STABLE
    AS $$
  SELECT
    COALESCE(d.source_filename, 'unknown') AS source_filename,
    (ARRAY_AGG(d.source_type ORDER BY d.created_at DESC))[1] AS source_type,
    BOOL_OR(
      COALESCE(d.metadata->>'file_url', d.metadata->>'image_url', d.metadata->>'audio_url')
        IS NOT NULL
    ) AS has_file,
    COUNT(*) AS chunks,
    CASE
      WHEN BOOL_OR(d.status = 'processing') THEN 'processing'
      WHEN BOOL_OR(d.status = 'failed') THEN 'failed'
      ELSE COALESCE((ARRAY_AGG(d.status ORDER BY d.created_at DESC))[1], 'completed')
    END AS status,
    MAX(d.created_at) AS created_at,
    d.folder_id
  FROM "public"."documents" d
  WHERE d.user_id = p_user_id
    AND (
      (p_folder_id IS NULL AND d.folder_id IS NULL)
      OR d.folder_id = p_folder_id
    )
  GROUP BY COALESCE(d.source_filename, 'unknown'), d.folder_id
  ORDER BY MAX(d.created_at) DESC;
  $$;

CREATE OR REPLACE FUNCTION "public"."list_documents_grouped_v2"(
    "p_user_id" "uuid",
    "p_folder_id" "uuid" DEFAULT NULL
) RETURNS TABLE(
    "source_filename" "text",
    "source_type" "text",
    "has_file" boolean,
    "chunks" bigint,
    "status" "text",
    "created_at" timestamp with time zone,
    "last_updated" timestamp with time zone,
    "folder_id" "uuid"
)
    LANGUAGE "sql" STABLE
    AS $$
  SELECT
    COALESCE(d.source_filename, 'unknown') AS source_filename,
    (ARRAY_AGG(d.source_type ORDER BY d.created_at DESC))[1] AS source_type,
    BOOL_OR(
      COALESCE(d.metadata->>'file_url', d.metadata->>'image_url', d.metadata->>'audio_url')
        IS NOT NULL
    ) AS has_file,
    COUNT(*) AS chunks,
    CASE
      WHEN BOOL_OR(d.status = 'processing') THEN 'processing'
      WHEN BOOL_OR(d.status = 'failed') THEN 'failed'
      ELSE COALESCE((ARRAY_AGG(d.status ORDER BY d.created_at DESC))[1], 'completed')
    END AS status,
    MAX(d.created_at) AS created_at,
    MAX(d.last_updated) AS last_updated,
    d.folder_id
  FROM "public"."documents" d
  WHERE d.user_id = p_user_id
    AND (
      (p_folder_id IS NULL AND d.folder_id IS NULL)
      OR d.folder_id = p_folder_id
    )
  GROUP BY COALESCE(d.source_filename, 'unknown'), d.folder_id
  ORDER BY MAX(d.last_updated) DESC, MAX(d.created_at) DESC;
  $$;
REVOKE ALL ON FUNCTION public.list_documents_grouped_v2(uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_documents_grouped_v2(uuid, uuid) TO service_role;



ALTER FUNCTION "public"."list_documents_grouped"("p_user_id" "uuid", "p_folder_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION "public"."folder_breadcrumbs"(
    "p_folder_id" "uuid",
    "p_user_id" "uuid"
) RETURNS TABLE(
    "id" "uuid",
    "name" "text",
    "kind" "text"
)
    LANGUAGE "sql" STABLE
    AS $$
  WITH RECURSIVE "chain" AS (
    SELECT f.id, f.name, f.parent_id, COALESCE(f.kind, 'folder') AS kind, 0 AS depth
    FROM "public"."folders" f
    WHERE f.id = p_folder_id AND f.user_id = p_user_id
    UNION ALL
    SELECT f.id, f.name, f.parent_id, COALESCE(f.kind, 'folder') AS kind, c.depth + 1
    FROM "public"."folders" f
    JOIN "chain" c ON f.id = c.parent_id
    WHERE f.user_id = p_user_id
  )
  SELECT id, name, kind
  FROM "chain"
  ORDER BY depth DESC;
  $$;


ALTER FUNCTION "public"."folder_breadcrumbs"("p_folder_id" "uuid", "p_user_id" "uuid") OWNER TO "postgres";


CREATE OR REPLACE FUNCTION public.set_briefing_section(
    p_folder_id uuid, p_user_id uuid, p_section text, p_value jsonb
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE
    v_latest record;
    v_sections jsonb;
BEGIN
    PERFORM 1 FROM public.folders
    WHERE id = p_folder_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RETURN false; END IF;
    SELECT * INTO v_latest FROM public.folder_summaries
    WHERE folder_id = p_folder_id AND user_id = p_user_id
    ORDER BY generated_at DESC LIMIT 1;
    IF NOT FOUND THEN RETURN false; END IF;
    v_sections := COALESCE(v_latest.content->'sections', '{}'::jsonb)
                  || COALESCE(v_latest.sections, '{}'::jsonb);
    IF (v_sections->p_section->'content') IS NOT DISTINCT FROM (p_value->'content') THEN
        RETURN true;
    END IF;
    v_sections := jsonb_set(v_sections, ARRAY[p_section], p_value, true);
    INSERT INTO public.folder_summaries (
        folder_id, user_id, kind, trigger, content, sections, briefing_schema_version, generated_at
    ) VALUES (
        p_folder_id, p_user_id, v_latest.kind, 'refresh',
        jsonb_set(v_latest.content, '{sections}', v_sections, true),
        v_sections, v_latest.briefing_schema_version,
        GREATEST(clock_timestamp(), v_latest.generated_at + interval '1 microsecond')
    );
    -- NULL content_hash is intentional: readers compute the canonical Python
    -- hash for legacy/SQL-written rows, avoiding divergent JSON serialization.
    RETURN true;
END;
$$;


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
    "last_updated" timestamp with time zone DEFAULT "now"() NOT NULL,
    "user_id" "uuid",
    "source_filename" "text",
    "content_hash" "text",
    "sections" "jsonb",
    "briefing_schema_version" integer,
    "status" "text" DEFAULT 'completed'::"text" NOT NULL,
    "source_type" "text",
    "fts" "tsvector" GENERATED ALWAYS AS ((setweight(to_tsvector('english'::"regconfig", COALESCE("source_filename", ''::"text")), 'A'::"char") || setweight(to_tsvector('english'::"regconfig", "content"), 'B'::"char"))) STORED,
    "folder_id" "uuid",
    "root_folder_id" "uuid",
    "notion_page_id" "text",
    "notion_last_edited_time" timestamp with time zone,
    "notion_parent_path" "text",
    "chunk_index" integer,
    CONSTRAINT "documents_status_check" CHECK (("status" = ANY (ARRAY['processing'::"text", 'completed'::"text", 'failed'::"text", 'deleted'::"text"])))
);


ALTER TABLE "public"."documents" OWNER TO "postgres";

CREATE OR REPLACE FUNCTION public.track_document_content_update()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  NEW.created_at := OLD.created_at;
  IF NEW.content IS DISTINCT FROM OLD.content OR NEW.content_hash IS DISTINCT FROM OLD.content_hash THEN
    NEW.last_updated := statement_timestamp();
  ELSE
    NEW.last_updated := OLD.last_updated;
  END IF;
  RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS documents_content_updated ON public.documents;
CREATE TRIGGER documents_content_updated BEFORE UPDATE ON public.documents
FOR EACH ROW EXECUTE FUNCTION public.track_document_content_update();


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
    "content_hash" "text",
    "trigger" "text",
    CONSTRAINT "folder_summaries_kind_check" CHECK (kind IN ('full', 'delta', 'seed', 'workspace_rollup', 'briefing')),
    CONSTRAINT "folder_summaries_trigger_check" CHECK (trigger IS NULL OR trigger IN ('cron_nightly', 'cron_weekly', 'manual', 'seed', 'edit', 'mcp_edit', 'restore', 'refresh', 'rollup_bootstrap:manual', 'rollup_bootstrap:cron_nightly', 'rollup_bootstrap:cron_weekly'))
);


ALTER TABLE "public"."folder_summaries" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."folders" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "name" "text" NOT NULL,
    "parent_id" "uuid",
    "user_id" "uuid" NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    "kind" "text" DEFAULT 'folder'::"text" NOT NULL,
    CONSTRAINT "folders_kind_check" CHECK (("kind" = ANY (ARRAY['folder'::"text", 'repo'::"text"])))
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



CREATE INDEX "idx_documents_user_folder_created" ON "public"."documents" USING "btree" ("user_id", "folder_id", "created_at" DESC);




CREATE UNIQUE INDEX "idx_ingestion_jobs_active_source" ON "public"."ingestion_jobs" USING "btree" ("kind", "source_ref") WHERE ("status" = ANY (ARRAY['queued'::"text", 'running'::"text"]));



CREATE INDEX "idx_ingestion_jobs_user_status" ON "public"."ingestion_jobs" USING "btree" ("user_id", "status");






CREATE UNIQUE INDEX "idx_notes_dedup" ON "public"."notes" USING "btree" ("user_id", "root_folder_id", "content_hash");



CREATE INDEX "idx_notes_user_scope" ON "public"."notes" USING "btree" ("user_id", "root_folder_id");



CREATE INDEX "idx_notion_sync_configs_user_id" ON "public"."notion_sync_configs" USING "btree" ("user_id");



CREATE INDEX "idx_retrieval_log_folder_id" ON "public"."retrieval_log" USING "btree" ("folder_id") WHERE ("folder_id" IS NOT NULL);



CREATE INDEX "idx_retrieval_log_user_id_created_at" ON "public"."retrieval_log" USING "btree" ("user_id", "created_at" DESC);



CREATE OR REPLACE TRIGGER "context_updated_at" BEFORE UPDATE ON "public"."context" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();



CREATE OR REPLACE TRIGGER "conversations_updated_at" BEFORE UPDATE ON "public"."conversations" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();




CREATE OR REPLACE TRIGGER "ingestion_jobs_updated_at" BEFORE UPDATE ON "public"."ingestion_jobs" FOR EACH ROW EXECUTE FUNCTION "public"."update_updated_at"();






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




ALTER TABLE "public"."messages" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."notes" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."notion_sync_configs" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."retrieval_log" ENABLE ROW LEVEL SECURITY;


CREATE POLICY "Users manage own git keys" ON "public"."user_git_keys" USING (("user_id" = "auth"."uid"())) WITH CHECK (("user_id" = "auth"."uid"()));


CREATE POLICY "Users manage own watched repos" ON "public"."watched_repos" USING (("user_id" = "auth"."uid"())) WITH CHECK (("user_id" = "auth"."uid"()));


CREATE POLICY "Users manage own code chunks" ON "public"."code_chunks" USING (("user_id" = "auth"."uid"())) WITH CHECK (("user_id" = "auth"."uid"()));


CREATE POLICY "Users manage own repo freshness" ON "public"."repo_freshness" USING (("user_id" = "auth"."uid"())) WITH CHECK (("user_id" = "auth"."uid"()));


ALTER TABLE "public"."user_git_keys" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."watched_repos" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."code_chunks" ENABLE ROW LEVEL SECURITY;


ALTER TABLE "public"."repo_freshness" ENABLE ROW LEVEL SECURITY;


GRANT USAGE ON SCHEMA "public" TO "postgres";
GRANT USAGE ON SCHEMA "public" TO "anon";
GRANT USAGE ON SCHEMA "public" TO "authenticated";
GRANT USAGE ON SCHEMA "public" TO "service_role";



-- NOT granted to anon/authenticated: this RPC bypasses RLS, so only the
-- backend's service_role may call it (see the REVOKE above).
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









-- ── Semantic code search ──────────────────────────────────────────────
-- Symbol-aware chunks of repo source code, embedded with voyage-code-3 in a
-- separate vector space from documents (different model => separate index).

CREATE TABLE IF NOT EXISTS "public"."code_chunks" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "folder_id" "uuid" NOT NULL,
    "file" "text" NOT NULL,
    "language" "text",
    "symbol" "text",
    "start_line" integer,
    "end_line" integer,
    "content" "text" NOT NULL,
    "file_hash" "text" NOT NULL,
    "embedding" "public"."vector"(1024),
    "embedding_model" "text" DEFAULT 'voyage-code-3' NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "code_chunks_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "code_chunks_user_id_fkey" FOREIGN KEY ("user_id")
        REFERENCES "auth"."users"("id") ON DELETE CASCADE,
    CONSTRAINT "code_chunks_folder_id_fkey" FOREIGN KEY ("folder_id")
        REFERENCES "public"."folders"("id") ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS "code_chunks_folder_file_idx"
    ON "public"."code_chunks" USING "btree" ("folder_id", "file");
CREATE INDEX IF NOT EXISTS "code_chunks_embedding_idx"
    ON "public"."code_chunks" USING "hnsw" ("embedding" "public"."vector_cosine_ops");

CREATE OR REPLACE FUNCTION "public"."code_search"(
    "query_embedding" "public"."vector",
    "match_count" integer DEFAULT 10,
    "filter_user_id" "uuid" DEFAULT NULL::"uuid",
    "filter_folder_ids" "uuid"[] DEFAULT NULL::"uuid"[],
    "filter_language" "text" DEFAULT NULL::"text"
) RETURNS TABLE(
    "id" "uuid",
    "folder_id" "uuid",
    "file" "text",
    "symbol" "text",
    "start_line" integer,
    "end_line" integer,
    "language" "text",
    "content" "text",
    "similarity" double precision,
    "created_at" timestamp with time zone
)
    LANGUAGE "sql" STABLE
    AS $$
    SELECT id, folder_id, file, symbol, start_line, end_line, language, content,
      1 - (embedding <=> query_embedding) AS similarity,
      created_at
    FROM code_chunks
    WHERE embedding IS NOT NULL
      AND (filter_user_id IS NULL OR user_id = filter_user_id)
      AND (filter_folder_ids IS NULL OR folder_id = ANY(filter_folder_ids))
      AND (filter_language IS NULL OR language = filter_language)
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
  $$;

ALTER TABLE "public"."code_chunks" OWNER TO "postgres";
ALTER FUNCTION "public"."code_search"(
    "public"."vector", integer, "uuid", "uuid"[], "text") OWNER TO "postgres";
-- Multi-user repo mihari: per-user git deploy identity + registry of
-- watched repos. Private keys and minted mihari api keys are stored
-- encrypted (Fernet, same master key mechanism as Notion tokens).

CREATE TABLE IF NOT EXISTS "public"."user_git_keys" (
    "user_id" "uuid" NOT NULL,
    "private_key_encrypted" "text" NOT NULL,
    "public_key" "text" NOT NULL,
    "fingerprint" "text" NOT NULL,
    "key_version" integer DEFAULT 1 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "last_used_at" timestamp with time zone,
    CONSTRAINT "user_git_keys_pkey" PRIMARY KEY ("user_id"),
    CONSTRAINT "user_git_keys_user_id_fkey" FOREIGN KEY ("user_id")
        REFERENCES "auth"."users"("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "public"."watched_repos" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "folder_id" "uuid" NOT NULL,
    "remote_url" "text" NOT NULL,
    "branch" "text" DEFAULT 'main' NOT NULL,
    "api_key_encrypted" "text",
    "last_sha" "text",
    "last_run_at" timestamp with time zone,
    "last_error" "text",
    "created_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    CONSTRAINT "watched_repos_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "watched_repos_user_remote_key" UNIQUE ("user_id", "remote_url"),
    CONSTRAINT "watched_repos_user_id_fkey" FOREIGN KEY ("user_id")
        REFERENCES "auth"."users"("id") ON DELETE CASCADE,
    CONSTRAINT "watched_repos_folder_id_fkey" FOREIGN KEY ("folder_id")
        REFERENCES "public"."folders"("id") ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS "watched_repos_user_idx"
    ON "public"."watched_repos" USING "btree" ("user_id");

ALTER TABLE "public"."user_git_keys" OWNER TO "postgres";
ALTER TABLE "public"."watched_repos" OWNER TO "postgres";
-- Freshness tracking for generated repo knowledge: the mihari compares the
-- clone's git history against briefing section timestamps and records which
-- prose sections are likely stale. Prose is NEVER auto-regenerated — the
-- warning surfaces in the UI and MCP, and regeneration stays an explicit
-- kioku CLI / coding-agent action.

CREATE TABLE IF NOT EXISTS "public"."repo_freshness" (
    "folder_id" "uuid" NOT NULL,
    "user_id" "uuid" NOT NULL,
    "head_sha" "text",
    "commits_behind" integer DEFAULT 0 NOT NULL,
    "stale_sections" "text"[] DEFAULT '{}' NOT NULL,
    "changed_files" integer DEFAULT 0 NOT NULL,
    "checked_at" timestamp with time zone DEFAULT "now"() NOT NULL,
    "index_refresh_started_at" timestamp with time zone,
    "sections_refresh_started_at" timestamp with time zone,
    "index_refresh_finished_at" timestamp with time zone,
    "index_refresh_error" text,
    "sections_refresh_finished_at" timestamp with time zone,
    "sections_refresh_error" text,
    "section_reviews" jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT "repo_freshness_pkey" PRIMARY KEY ("folder_id"),
    CONSTRAINT "repo_freshness_folder_id_fkey" FOREIGN KEY ("folder_id")
        REFERENCES "public"."folders"("id") ON DELETE CASCADE,
    CONSTRAINT "repo_freshness_user_id_fkey" FOREIGN KEY ("user_id")
        REFERENCES "auth"."users"("id") ON DELETE CASCADE
);

ALTER TABLE "public"."repo_freshness" OWNER TO "postgres";


CREATE TABLE IF NOT EXISTS "public"."chat_usage" (
    "id" "uuid" DEFAULT "gen_random_uuid"() NOT NULL,
    "user_id" "uuid" NOT NULL,
    "conversation_id" "uuid" NOT NULL,
    "model" "text" NOT NULL,
    "input_tokens" integer DEFAULT 0 NOT NULL,
    "output_tokens" integer DEFAULT 0 NOT NULL,
    "created_at" timestamp with time zone DEFAULT "now"(),
    CONSTRAINT "chat_usage_pkey" PRIMARY KEY ("id")
);

ALTER TABLE "public"."chat_usage" OWNER TO "postgres";

CREATE INDEX IF NOT EXISTS "chat_usage_user_created_idx" ON "public"."chat_usage" ("user_id", "created_at");
CREATE INDEX IF NOT EXISTS "chat_usage_user_conversation_idx" ON "public"."chat_usage" ("user_id", "conversation_id");

ALTER TABLE "public"."chat_usage" ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users manage own chat usage" ON "public"."chat_usage" USING (("user_id" = "auth"."uid"())) WITH CHECK (("user_id" = "auth"."uid"()));

-- Assistant-message debug trace (Inspect card) and inline-citation registry;
-- both nullable, set only when the turn produced them. See migrations
-- 20260930010000_messages_debug.sql and 20261015010000_messages_citations.sql.
ALTER TABLE "public"."messages" ADD COLUMN IF NOT EXISTS "debug" "jsonb";
ALTER TABLE "public"."messages" ADD COLUMN IF NOT EXISTS "citations" "jsonb";

-- Manabi credentials are scoped only to machine connection presence.
CREATE TABLE IF NOT EXISTS public.remote_machines (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    id uuid NOT NULL,
    token_hash text NOT NULL,
    name text NOT NULL,
    platform text NOT NULL,
    version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    connected_at timestamptz,
    last_seen timestamptz,
    connected boolean NOT NULL DEFAULT false,
    connection_id uuid,
    PRIMARY KEY (user_id, id)
);
ALTER TABLE public.remote_machines ENABLE ROW LEVEL SECURITY;
-- All access is through authenticated backend routes; no direct client grants.
REVOKE ALL ON public.remote_machines FROM anon, authenticated;
GRANT ALL ON public.remote_machines TO service_role;
-- Current configured-repository inventory only; no agent sessions or memories.
ALTER TABLE public.remote_machines
    ADD COLUMN IF NOT EXISTS custom_name text,
    ADD COLUMN IF NOT EXISTS os_name text,
    ADD COLUMN IF NOT EXISTS os_id text,
    ADD COLUMN IF NOT EXISTS architecture text,
    ADD COLUMN IF NOT EXISTS inventory jsonb,
    ADD COLUMN IF NOT EXISTS inventory_updated_at timestamptz,
    ADD COLUMN IF NOT EXISTS warnings jsonb NOT NULL DEFAULT '[]'::jsonb;
-- One active private Markdown journal per user, repository, and local day.
CREATE TABLE IF NOT EXISTS public.agent_journal_days (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
    journal_date date NOT NULL,
    storage_path text NOT NULL,
    content_sha256 text NOT NULL,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision > 0),
    entry_count integer NOT NULL DEFAULT 0 CHECK (entry_count >= 0),
    agents text[] NOT NULL DEFAULT '{}',
    first_entry_at timestamptz,
    last_entry_at timestamptz,
    synced_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, folder_id, journal_date)
);

CREATE INDEX IF NOT EXISTS agent_journal_days_user_date_idx
    ON public.agent_journal_days (user_id, journal_date DESC);
ALTER TABLE public.agent_journal_days ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own agent journals" ON public.agent_journal_days
    FOR SELECT TO authenticated USING (auth.uid() = user_id);
REVOKE ALL ON public.agent_journal_days FROM anon, authenticated;
GRANT SELECT ON public.agent_journal_days TO authenticated;
GRANT ALL ON public.agent_journal_days TO service_role;

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('agent-journals', 'agent-journals', false, 5242880, ARRAY['text/markdown'])
ON CONFLICT (id) DO NOTHING;

-- CAS is performed under a lock on the owning folder row. Upload the new
-- content-addressed object first, then publish its path atomically here.
CREATE OR REPLACE FUNCTION public.publish_agent_journal(
    p_user_id uuid, p_folder_id uuid, p_date date,
    p_expected_revision bigint, p_storage_path text, p_sha256 text,
    p_entry_count integer, p_agents text[],
    p_first_entry_at timestamptz, p_last_entry_at timestamptz
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_current public.agent_journal_days%ROWTYPE;
    v_revision bigint;
BEGIN
    PERFORM 1 FROM public.folders
    WHERE id = p_folder_id AND user_id = p_user_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Repository not found for user'; END IF;

    SELECT * INTO v_current FROM public.agent_journal_days
    WHERE user_id = p_user_id AND folder_id = p_folder_id AND journal_date = p_date
    FOR UPDATE;
    IF FOUND AND v_current.content_sha256 = p_sha256 THEN
        RETURN jsonb_build_object('status', 'unchanged', 'revision', v_current.revision,
                                  'storage_path', v_current.storage_path);
    END IF;
    v_revision := COALESCE(v_current.revision, 0);
    IF v_revision <> p_expected_revision THEN
        RETURN jsonb_build_object('status', 'conflict', 'revision', v_revision,
                                  'storage_path', v_current.storage_path);
    END IF;

    INSERT INTO public.agent_journal_days AS j
        (user_id, folder_id, journal_date, storage_path, content_sha256,
         revision, entry_count, agents, first_entry_at, last_entry_at, synced_at)
    VALUES
        (p_user_id, p_folder_id, p_date, p_storage_path, p_sha256,
         v_revision + 1, p_entry_count, p_agents, p_first_entry_at, p_last_entry_at, now())
    ON CONFLICT (user_id, folder_id, journal_date) DO UPDATE SET
        storage_path = EXCLUDED.storage_path,
        content_sha256 = EXCLUDED.content_sha256,
        revision = EXCLUDED.revision,
        entry_count = EXCLUDED.entry_count,
        agents = EXCLUDED.agents,
        first_entry_at = EXCLUDED.first_entry_at,
        last_entry_at = EXCLUDED.last_entry_at,
        synced_at = now();
    RETURN jsonb_build_object('status', 'ok', 'revision', v_revision + 1,
                              'previous_path', v_current.storage_path,
                              'storage_path', p_storage_path);
END;
$$;
REVOKE ALL ON FUNCTION public.publish_agent_journal(uuid, uuid, date, bigint, text, text, integer, text[], timestamptz, timestamptz) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.publish_agent_journal(uuid, uuid, date, bigint, text, text, integer, text[], timestamptz, timestamptz) TO service_role;
-- Original agent evidence is private, immutable data; no inference providers involved.
CREATE TABLE public.agent_evidence_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
    agent text NOT NULL CHECK (agent IN ('claude_code', 'codex')),
    native_session_id text NOT NULL,
    manifest_path text,
    parent_session_id uuid,
    root_session_id uuid NOT NULL,
    manifest_json jsonb NOT NULL DEFAULT '{"schema":1,"segments":[],"attachments":[],"gaps":[]}',
    manifest_revision bigint NOT NULL DEFAULT 0,
    manifest_sha256 text,
    materialized_revision bigint NOT NULL DEFAULT -1,
    indexed_revision bigint NOT NULL DEFAULT 0,
    index_generation bigint NOT NULL DEFAULT 0,
    parser_version integer NOT NULL DEFAULT 0,
    first_event_at timestamptz,
    last_event_at timestamptz,
    captured_at timestamptz,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    event_count bigint NOT NULL DEFAULT 0,
    capture_status text NOT NULL DEFAULT 'pending',
    index_status text NOT NULL DEFAULT 'pending',
    lifecycle jsonb NOT NULL DEFAULT '{}',
    gaps jsonb NOT NULL DEFAULT '[]',
    producer_gaps jsonb NOT NULL DEFAULT '{}',
    deleted_at timestamptz,
    purged_at timestamptz,
    UNIQUE(user_id, folder_id, agent, native_session_id),
    UNIQUE(id, user_id, folder_id),
    UNIQUE(id, user_id, folder_id, agent),
    FOREIGN KEY(parent_session_id,user_id,folder_id,agent)
        REFERENCES public.agent_evidence_sessions(id,user_id,folder_id,agent)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY(root_session_id,user_id,folder_id,agent)
        REFERENCES public.agent_evidence_sessions(id,user_id,folder_id,agent)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (parent_session_id IS NULL OR parent_session_id <> id)
);
CREATE INDEX agent_evidence_session_activity ON public.agent_evidence_sessions
    (user_id, folder_id, last_event_at DESC, id);
CREATE INDEX agent_evidence_session_parent ON public.agent_evidence_sessions(parent_session_id);

CREATE TABLE public.agent_evidence_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    folder_id uuid NOT NULL,
    session_id uuid NOT NULL,
    batch_id text NOT NULL,
    request_hash text NOT NULL,
    request_json jsonb NOT NULL,
    state text NOT NULL DEFAULT 'staged',
    committed_revision bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    lease_until timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    error_code text,
    cleanup_paths jsonb NOT NULL DEFAULT '[]',
    UNIQUE(user_id, batch_id),
    FOREIGN KEY(session_id, user_id, folder_id)
        REFERENCES public.agent_evidence_sessions(id, user_id, folder_id) ON DELETE CASCADE
);
CREATE INDEX agent_evidence_batch_jobs ON public.agent_evidence_batches(state, updated_at);

CREATE TABLE public.agent_evidence_objects (
    session_id uuid NOT NULL,
    user_id uuid NOT NULL,
    folder_id uuid NOT NULL,
    object_id text NOT NULL,
    descriptor jsonb NOT NULL,
    producer_id text NOT NULL,
    stream_id text NOT NULL,
    generation integer NOT NULL CHECK (generation > 0),
    kind text NOT NULL CHECK (kind IN ('segment', 'attachment')),
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    byte_length bigint NOT NULL CHECK (byte_length > 0 AND byte_length <= 67108864),
    storage_path text,
    uploaded_at timestamptz,
    upload_nonce uuid NOT NULL DEFAULT gen_random_uuid(),
    upload_lease_until timestamptz,
    committed_revision bigint,
    first_record bigint GENERATED ALWAYS AS ((descriptor->>'first_record')::bigint) STORED,
    indexed_parser_version integer NOT NULL DEFAULT 0,
    parser_state jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY(session_id, object_id),
    FOREIGN KEY(session_id, user_id, folder_id)
        REFERENCES public.agent_evidence_sessions(id, user_id, folder_id) ON DELETE CASCADE
);
CREATE INDEX agent_evidence_object_order ON public.agent_evidence_objects
    (session_id, stream_id, generation, first_record);

CREATE TABLE public.agent_evidence_events (
    session_id uuid NOT NULL,
    user_id uuid NOT NULL,
    folder_id uuid NOT NULL,
    event_id text NOT NULL,
    object_id text NOT NULL,
    stream_id text NOT NULL,
    generation integer NOT NULL,
    record_sequence bigint NOT NULL,
    byte_offset bigint NOT NULL,
    byte_length bigint NOT NULL,
    event_at timestamptz,
    role text NOT NULL,
    event_type text NOT NULL,
    native_id text,
    turn_id text,
    call_id text,
    parent_id text,
    inherited boolean NOT NULL DEFAULT false,
    displayable boolean NOT NULL DEFAULT true,
    content_preview text NOT NULL DEFAULT '',
    content_length bigint NOT NULL DEFAULT 0,
    source_truncated boolean NOT NULL DEFAULT false,
    parser_version integer NOT NULL,
    position text GENERATED ALWAYS AS
        (stream_id || '/' || lpad(generation::text,10,'0') || '/' || lpad(record_sequence::text,20,'0')) STORED,
    PRIMARY KEY(session_id, event_id),
    FOREIGN KEY(session_id, user_id, folder_id)
        REFERENCES public.agent_evidence_sessions(id, user_id, folder_id) ON DELETE CASCADE,
    FOREIGN KEY(session_id, object_id)
        REFERENCES public.agent_evidence_objects(session_id, object_id) ON DELETE CASCADE
);
CREATE INDEX agent_evidence_event_order ON public.agent_evidence_events
    (session_id, stream_id, generation, record_sequence);
CREATE INDEX agent_evidence_event_time ON public.agent_evidence_events(session_id, event_at);
CREATE INDEX agent_evidence_event_position ON public.agent_evidence_events(session_id, position);

CREATE TABLE public.agent_evidence_journal_links (
    user_id uuid NOT NULL,
    folder_id uuid NOT NULL,
    journal_entry_id text NOT NULL,
    journal_date date NOT NULL,
    session_id uuid NOT NULL,
    start_event_id text NOT NULL,
    end_event_id text,
    PRIMARY KEY(user_id, folder_id, journal_entry_id),
    FOREIGN KEY(session_id, user_id, folder_id)
        REFERENCES public.agent_evidence_sessions(id, user_id, folder_id) ON DELETE CASCADE
);

INSERT INTO storage.buckets(id, name, public, file_size_limit)
VALUES ('agent-evidence', 'agent-evidence', false, 67108864)
ON CONFLICT(id) DO UPDATE SET public = false, file_size_limit = 67108864;

-- Every mutation is service-role only and verifies ownership independently of HTTP.
CREATE OR REPLACE FUNCTION public.prepare_agent_evidence(p_user_id uuid, p_request jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_folder uuid := (p_request->>'folder_id')::uuid;
    v_agent text := p_request->>'agent';
    v_native text := p_request->>'native_session_id';
    v_root_native text := COALESCE(p_request->>'native_root_session_id', v_native);
    v_parent_native text := p_request->>'native_parent_session_id';
    v_session public.agent_evidence_sessions%ROWTYPE;
    v_root public.agent_evidence_sessions%ROWTYPE;
    v_parent public.agent_evidence_sessions%ROWTYPE;
    v_batch public.agent_evidence_batches%ROWTYPE;
    v_existing public.agent_evidence_objects%ROWTYPE;
    v_hash text := encode(sha256(convert_to(p_request::text, 'UTF8')), 'hex');
    v_id uuid;
    obj jsonb;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.folders
                   WHERE id=v_folder AND user_id=p_user_id AND kind='repo') THEN
        RAISE EXCEPTION 'evidence_scope_denied' USING ERRCODE='42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text || v_folder::text || v_agent, 0));
    SELECT * INTO v_batch FROM public.agent_evidence_batches
        WHERE user_id=p_user_id AND batch_id=p_request->>'batch_id';
    IF FOUND THEN
        IF v_batch.request_hash <> v_hash THEN
            RAISE EXCEPTION 'evidence_batch_conflict' USING ERRCODE='23505';
        END IF;
        RETURN jsonb_build_object('batch_id', v_batch.batch_id, 'session_id', v_batch.session_id);
    END IF;
    IF v_parent_native=v_native OR (v_parent_native IS NULL AND v_root_native<>v_native) THEN
        RAISE EXCEPTION 'evidence_invalid_ancestry' USING ERRCODE='23514';
    END IF;
    SELECT * INTO v_root FROM public.agent_evidence_sessions
      WHERE user_id=p_user_id AND folder_id=v_folder AND agent=v_agent
        AND native_session_id=v_root_native;
    IF NOT FOUND THEN
        v_id := gen_random_uuid();
        INSERT INTO public.agent_evidence_sessions(id,user_id,folder_id,agent,native_session_id,root_session_id)
          VALUES(v_id,p_user_id,v_folder,v_agent,v_root_native,v_id) RETURNING * INTO v_root;
    END IF;
    IF v_root.parent_session_id IS NOT NULL OR v_root.root_session_id<>v_root.id THEN
        RAISE EXCEPTION 'evidence_invalid_ancestry';
    END IF;
    IF v_root.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION 'evidence_deleted' USING ERRCODE='23514';
    END IF;
    IF v_root.manifest_path IS NULL THEN
        UPDATE public.agent_evidence_sessions SET manifest_path=p_user_id::text||'/'||v_folder::text||'/'||v_agent||'/'||v_root_native||'/manifest.json'
          WHERE id=v_root.id RETURNING * INTO v_root;
    END IF;
    IF v_parent_native IS NOT NULL THEN
        SELECT * INTO v_parent FROM public.agent_evidence_sessions
          WHERE user_id=p_user_id AND folder_id=v_folder AND agent=v_agent
            AND native_session_id=v_parent_native AND root_session_id=v_root.id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'evidence_dependency_pending' USING ERRCODE='23514';
        END IF;
        IF v_parent.deleted_at IS NOT NULL THEN
            RAISE EXCEPTION 'evidence_deleted' USING ERRCODE='23514';
        END IF;
    END IF;
    SELECT * INTO v_session FROM public.agent_evidence_sessions
      WHERE user_id=p_user_id AND folder_id=v_folder AND agent=v_agent AND native_session_id=v_native;
    IF NOT FOUND THEN
        INSERT INTO public.agent_evidence_sessions(user_id,folder_id,agent,native_session_id,
            parent_session_id,root_session_id)
        VALUES(p_user_id,v_folder,v_agent,v_native,v_parent.id,v_root.id) RETURNING * INTO v_session;
    END IF;
    IF v_session.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION 'evidence_deleted' USING ERRCODE='23514';
    END IF;
    IF v_session.root_session_id<>v_root.id OR v_session.parent_session_id IS DISTINCT FROM v_parent.id THEN
        RAISE EXCEPTION 'evidence_invalid_ancestry' USING ERRCODE='23514';
    END IF;
    UPDATE public.agent_evidence_sessions SET manifest_path=
      CASE WHEN v_parent.id IS NULL THEN p_user_id::text||'/'||v_folder::text||'/'||v_agent||'/'||v_native
           ELSE left(v_parent.manifest_path,length(v_parent.manifest_path)-14)||'/subagents/'||v_native END
      ||'/manifest.json' WHERE id=v_session.id;
    FOR obj IN SELECT * FROM jsonb_array_elements(p_request->'objects') LOOP
        SELECT * INTO v_existing FROM public.agent_evidence_objects
          WHERE session_id=v_session.id AND object_id=obj->>'id';
        IF FOUND AND (v_existing.descriptor<>obj OR v_existing.producer_id<>p_request->>'producer_id') THEN
            RAISE EXCEPTION 'evidence_object_conflict' USING ERRCODE='23505';
        END IF;
        IF EXISTS (SELECT 1 FROM public.agent_evidence_objects
          WHERE session_id=v_session.id AND stream_id=obj->>'stream_id'
            AND producer_id<>p_request->>'producer_id') THEN
            RAISE EXCEPTION 'evidence_stream_conflict' USING ERRCODE='23505';
        END IF;
        INSERT INTO public.agent_evidence_objects(session_id,user_id,folder_id,object_id,descriptor,
            producer_id,stream_id,generation,kind,sha256,byte_length)
        VALUES(v_session.id,p_user_id,v_folder,obj->>'id',obj,p_request->>'producer_id',
            obj->>'stream_id',(obj->>'generation')::integer,obj->>'kind',obj->>'sha256',
            (obj->>'byte_length')::bigint) ON CONFLICT DO NOTHING;
    END LOOP;
    INSERT INTO public.agent_evidence_batches(user_id,folder_id,session_id,batch_id,request_hash,request_json)
      VALUES(p_user_id,v_folder,v_session.id,p_request->>'batch_id',v_hash,p_request)
      RETURNING * INTO v_batch;
    RETURN jsonb_build_object('batch_id',v_batch.batch_id,'session_id',v_session.id);
END $$;

CREATE OR REPLACE FUNCTION public.commit_agent_evidence(p_user_id uuid, p_batch_id text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    b public.agent_evidence_batches%ROWTYPE;
    s public.agent_evidence_sessions%ROWTYPE;
    o public.agent_evidence_objects%ROWTYPE;
    d jsonb;
    link jsonb;
    v_revision bigint;
    v_manifest jsonb;
    v_validated text[] := '{}';
    v_producer_gaps jsonb;
    v_gaps jsonb;
    v_lifecycle jsonb;
BEGIN
    SELECT * INTO b FROM public.agent_evidence_batches WHERE user_id=p_user_id AND batch_id=p_batch_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'evidence_not_found'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text || b.folder_id::text ||
        (SELECT agent FROM public.agent_evidence_sessions WHERE id=b.session_id), 0));
    SELECT * INTO b FROM public.agent_evidence_batches WHERE id=b.id FOR UPDATE;
    SELECT * INTO s FROM public.agent_evidence_sessions WHERE id=b.session_id FOR UPDATE;
    IF s.deleted_at IS NOT NULL THEN RAISE EXCEPTION 'evidence_deleted'; END IF;
    IF b.committed_revision IS NOT NULL THEN
        RETURN jsonb_build_object('status','unchanged','session_id',s.id,'revision',b.committed_revision,
            'index_status',s.index_status);
    END IF;
    IF s.manifest_revision<>(b.request_json->>'base_revision')::bigint THEN
        RETURN jsonb_build_object('status','conflict','code','revision_conflict',
            'revision',s.manifest_revision,'session_id',s.id);
    END IF;
    FOR d IN SELECT * FROM jsonb_array_elements(b.request_json->'objects') LOOP
        SELECT * INTO o FROM public.agent_evidence_objects WHERE session_id=s.id AND object_id=d->>'id';
        IF o.uploaded_at IS NULL THEN
            RETURN jsonb_build_object('status','incomplete','code','missing_object','object_id',o.object_id);
        END IF;
        IF o.kind='segment' AND o.committed_revision IS NULL THEN
            IF (d->>'source_start')::bigint=0 THEN
                IF (d->>'first_record')::bigint<>1 THEN RAISE EXCEPTION 'evidence_invalid_range'; END IF;
            ELSIF NOT EXISTS (SELECT 1 FROM public.agent_evidence_objects prior
                WHERE prior.session_id=s.id AND prior.stream_id=o.stream_id AND prior.generation=o.generation
                AND prior.kind='segment' AND (prior.committed_revision IS NOT NULL
                    OR prior.object_id=ANY(v_validated))
                AND (prior.descriptor->>'source_end')::bigint=(d->>'source_start')::bigint
                AND (prior.descriptor->>'last_record')::bigint=(d->>'first_record')::bigint-1) THEN
                RETURN jsonb_build_object('status','dependency_pending','code','dependency_pending');
            END IF;
            IF EXISTS (SELECT 1 FROM public.agent_evidence_objects prior
              WHERE prior.session_id=s.id AND prior.object_id<>o.object_id AND prior.kind='segment'
                AND prior.stream_id=o.stream_id AND prior.generation=o.generation
                AND (prior.committed_revision IS NOT NULL OR prior.object_id=ANY(v_validated))
                AND int8range((prior.descriptor->>'source_start')::bigint,
                              (prior.descriptor->>'source_end')::bigint,'[)') &&
                    int8range((d->>'source_start')::bigint,(d->>'source_end')::bigint,'[)')) THEN
                RAISE EXCEPTION 'evidence_range_conflict';
            END IF;
            v_validated := array_append(v_validated,o.object_id);
        END IF;
    END LOOP;
    v_revision := s.manifest_revision+1;
    UPDATE public.agent_evidence_objects SET committed_revision=COALESCE(committed_revision,v_revision)
      WHERE session_id=s.id AND object_id IN (SELECT value->>'id' FROM jsonb_array_elements(b.request_json->'objects'));
    FOR link IN SELECT * FROM jsonb_array_elements(COALESCE(b.request_json->'journal_links','[]')) LOOP
        -- Association is supplemental. Conflicting/late aliases cannot reject raw evidence.
        INSERT INTO public.agent_evidence_journal_links
          VALUES(p_user_id,s.folder_id,link->>'journal_entry_id',(link->>'journal_date')::date,
                 s.id,link->>'start_event_id',link->>'end_event_id')
        ON CONFLICT (user_id,folder_id,journal_entry_id) DO UPDATE
        SET end_event_id=EXCLUDED.end_event_id
        WHERE agent_evidence_journal_links.session_id=EXCLUDED.session_id
          AND agent_evidence_journal_links.start_event_id=EXCLUDED.start_event_id
          AND EXCLUDED.end_event_id IS NOT NULL
          AND (agent_evidence_journal_links.end_event_id IS NULL
            OR NOT EXISTS(SELECT 1 FROM public.agent_evidence_events old_end
              WHERE old_end.session_id=s.id AND old_end.event_id=agent_evidence_journal_links.end_event_id)
            OR EXISTS(SELECT 1 FROM public.agent_evidence_events new_end
              JOIN public.agent_evidence_events old_end ON old_end.session_id=new_end.session_id
              WHERE new_end.session_id=s.id AND new_end.event_id=EXCLUDED.end_event_id
                AND old_end.event_id=agent_evidence_journal_links.end_event_id
                AND new_end.position>=old_end.position));
    END LOOP;
    v_producer_gaps := jsonb_set(s.producer_gaps,ARRAY[b.request_json->>'producer_id'],
        COALESCE(b.request_json->'gaps','[]'),true);
    SELECT COALESCE(jsonb_agg(DISTINCT gap),'[]') INTO v_gaps
      FROM jsonb_each(v_producer_gaps) producer, jsonb_array_elements(producer.value) gap;
    v_lifecycle := s.lifecycle || COALESCE(b.request_json->'lifecycle','{}');
    SELECT jsonb_build_object('schema',1,'revision',v_revision,'agent',s.agent,
        'native_session_id',s.native_session_id,'parent_session_id',s.parent_session_id,
        'gaps',v_gaps,'lifecycle',v_lifecycle,
        'children',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',child.id,
            'native_session_id',child.native_session_id) ORDER BY child.id)
            FROM public.agent_evidence_sessions child WHERE child.parent_session_id=s.id
            AND child.deleted_at IS NULL),'[]'),
        'segments',COALESCE(jsonb_agg(descriptor || jsonb_build_object('storage_path',storage_path)
            ORDER BY stream_id,generation,
            (descriptor->>'source_start')::bigint) FILTER(WHERE kind='segment'),'[]'),
        'attachments',COALESCE(jsonb_agg(descriptor || jsonb_build_object('storage_path',storage_path)
            ORDER BY object_id)
            FILTER(WHERE kind='attachment'),'[]')) INTO v_manifest
      FROM public.agent_evidence_objects WHERE session_id=s.id AND committed_revision IS NOT NULL;
    UPDATE public.agent_evidence_sessions SET manifest_json=v_manifest,
        manifest_sha256=encode(sha256(convert_to(v_manifest::text,'UTF8')),'hex'),manifest_revision=v_revision,
        index_status=CASE WHEN EXISTS(SELECT 1 FROM public.agent_evidence_objects
          WHERE session_id=s.id AND kind='segment' AND committed_revision IS NOT NULL
            AND indexed_parser_version<1) THEN 'pending' ELSE 'ready' END,
        indexed_revision=CASE WHEN EXISTS(SELECT 1 FROM public.agent_evidence_objects
          WHERE session_id=s.id AND kind='segment' AND committed_revision IS NOT NULL
            AND indexed_parser_version<1) THEN indexed_revision ELSE v_revision END,
        capture_status='captured',captured_at=now(),ingested_at=now(),
        lifecycle=v_lifecycle,producer_gaps=v_producer_gaps,gaps=v_gaps WHERE id=s.id;
    IF s.parent_session_id IS NOT NULL THEN
      UPDATE public.agent_evidence_sessions parent SET
        manifest_json=jsonb_set(jsonb_set(parent.manifest_json,'{children}',
          COALESCE((SELECT jsonb_agg(jsonb_build_object('id',child.id,'native_session_id',child.native_session_id)
            ORDER BY child.id) FROM public.agent_evidence_sessions child
            WHERE child.parent_session_id=parent.id AND child.deleted_at IS NULL),'[]')),
          '{revision}',to_jsonb(parent.manifest_revision+1)),
        manifest_revision=parent.manifest_revision+1,manifest_sha256=NULL
      WHERE parent.id=s.parent_session_id;
      UPDATE public.agent_evidence_sessions SET
        manifest_sha256=encode(sha256(convert_to(manifest_json::text,'UTF8')),'hex')
        WHERE id=s.parent_session_id;
    END IF;
    UPDATE public.agent_evidence_batches SET committed_revision=v_revision,state='pending',updated_at=now()
      WHERE id=b.id;
    RETURN jsonb_build_object('status','accepted','session_id',s.id,'revision',v_revision,'index_status',
        (SELECT index_status FROM public.agent_evidence_sessions WHERE id=s.id));
END $$;

CREATE OR REPLACE FUNCTION public.claim_agent_evidence_upload(p_user_id uuid,p_session_id uuid,p_object_id text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE s public.agent_evidence_sessions%ROWTYPE; o public.agent_evidence_objects%ROWTYPE;
BEGIN
    SELECT * INTO s FROM public.agent_evidence_sessions WHERE id=p_session_id AND user_id=p_user_id FOR UPDATE;
    IF NOT FOUND OR s.deleted_at IS NOT NULL THEN RAISE EXCEPTION 'evidence_deleted'; END IF;
    SELECT * INTO o FROM public.agent_evidence_objects WHERE session_id=s.id AND object_id=p_object_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'evidence_not_found'; END IF;
    UPDATE public.agent_evidence_objects SET upload_lease_until=now()+interval '3 minutes',
        storage_path=COALESCE(storage_path,left(s.manifest_path,length(s.manifest_path)-14)||
          CASE WHEN o.kind='segment' THEN '/segments/' ELSE '/attachments/' END||o.object_id||'-'||o.upload_nonce::text||
          CASE WHEN o.kind='segment' THEN '.jsonl' ELSE '' END)
        WHERE session_id=s.id AND object_id=p_object_id;
    RETURN jsonb_build_object('nonce',o.upload_nonce,'uploaded',o.uploaded_at IS NOT NULL);
END $$;

CREATE OR REPLACE FUNCTION public.finish_agent_evidence_upload(
    p_user_id uuid,p_session_id uuid,p_object_id text,p_nonce uuid,p_path text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
    PERFORM 1 FROM public.agent_evidence_sessions WHERE id=p_session_id AND user_id=p_user_id
        AND deleted_at IS NULL FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'evidence_deleted'; END IF;
    UPDATE public.agent_evidence_objects SET storage_path=p_path,uploaded_at=now(),upload_lease_until=NULL
      WHERE session_id=p_session_id AND user_id=p_user_id AND object_id=p_object_id AND upload_nonce=p_nonce;
    IF NOT FOUND THEN RAISE EXCEPTION 'evidence_upload_expired'; END IF;
END $$;

CREATE OR REPLACE FUNCTION public.expire_agent_evidence_batch(p_batch_row_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE b public.agent_evidence_batches%ROWTYPE; o public.agent_evidence_objects%ROWTYPE;
    paths jsonb := '[]';
BEGIN
    SELECT * INTO b FROM public.agent_evidence_batches WHERE id=p_batch_row_id;
    IF NOT FOUND THEN RETURN paths; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(b.user_id::text || b.folder_id::text ||
        (SELECT agent FROM public.agent_evidence_sessions WHERE id=b.session_id),0));
    SELECT * INTO b FROM public.agent_evidence_batches WHERE id=b.id FOR UPDATE;
    IF b.committed_revision IS NOT NULL OR b.created_at>now()-interval '7 days' THEN RETURN paths; END IF;
    paths:=b.cleanup_paths;
    FOR o IN SELECT * FROM public.agent_evidence_objects obj WHERE obj.session_id=b.session_id
        AND obj.committed_revision IS NULL AND (obj.upload_lease_until IS NULL OR obj.upload_lease_until<now())
        AND NOT EXISTS(SELECT 1 FROM public.agent_evidence_batches fresh WHERE fresh.session_id=obj.session_id
            AND fresh.created_at>now()-interval '7 days' AND fresh.state='staged'
            AND fresh.request_json->'objects' @> jsonb_build_array(jsonb_build_object('id',obj.object_id)))
        FOR UPDATE LOOP
        IF o.storage_path IS NOT NULL THEN paths:=paths || to_jsonb(o.storage_path); END IF;
        -- A new upload receives a new physical key. An expired cleanup can never
        -- delete bytes belonging to a subsequent acknowledged upload.
        UPDATE public.agent_evidence_objects SET uploaded_at=NULL,storage_path=NULL,
            upload_nonce=gen_random_uuid(),upload_lease_until=NULL WHERE session_id=o.session_id AND object_id=o.object_id;
    END LOOP;
    UPDATE public.agent_evidence_batches SET state='expired',cleanup_paths=paths WHERE id=b.id;
    RETURN paths;
END $$;

CREATE OR REPLACE FUNCTION public.publish_agent_evidence_index(
    p_session_id uuid, p_object_id text, p_events jsonb, p_state jsonb, p_parser_version integer,
    p_complete boolean DEFAULT true)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE s public.agent_evidence_sessions%ROWTYPE; e jsonb;
BEGIN
    SELECT * INTO s FROM public.agent_evidence_sessions WHERE id=p_session_id FOR UPDATE;
    IF NOT FOUND OR s.deleted_at IS NOT NULL THEN RETURN; END IF;
    IF NOT EXISTS(SELECT 1 FROM public.agent_evidence_objects WHERE session_id=s.id
      AND object_id=p_object_id AND committed_revision IS NOT NULL) THEN
        RAISE EXCEPTION 'evidence_not_committed';
    END IF;
    FOR e IN SELECT * FROM jsonb_array_elements(p_events) LOOP
      INSERT INTO public.agent_evidence_events(session_id,user_id,folder_id,event_id,object_id,
          stream_id,generation,record_sequence,byte_offset,byte_length,event_at,role,event_type,
          native_id,turn_id,call_id,parent_id,inherited,displayable,content_preview,content_length,source_truncated,parser_version)
      VALUES(s.id,s.user_id,s.folder_id,e->>'event_id',p_object_id,e->>'stream_id',
          (e->>'generation')::integer,(e->>'record_sequence')::bigint,(e->>'byte_offset')::bigint,
          (e->>'byte_length')::bigint,(e->>'event_at')::timestamptz,e->>'role',e->>'event_type',
          e->>'native_id',e->>'turn_id',e->>'call_id',e->>'parent_id',
          COALESCE((e->>'inherited')::boolean,false),COALESCE((e->>'displayable')::boolean,true),
          e->>'content_preview',COALESCE((e->>'content_length')::bigint,0),
          COALESCE((e->>'source_truncated')::boolean,false),p_parser_version)
      ON CONFLICT(session_id,event_id) DO UPDATE SET
          content_preview=excluded.content_preview,role=excluded.role,event_type=excluded.event_type,
          displayable=excluded.displayable,inherited=excluded.inherited,
          source_truncated=excluded.source_truncated,content_length=excluded.content_length,
          parser_version=excluded.parser_version
      WHERE agent_evidence_events.parser_version<=excluded.parser_version;
    END LOOP;
    -- Only established native call identities establish duplicate tool-result representations.
    -- Prefer the richer retained result; all alternatives stay available through raw-records.
    UPDATE public.agent_evidence_events e SET displayable=false
      WHERE e.session_id=s.id AND e.event_type='tool_result' AND e.call_id IS NOT NULL
      AND EXISTS(SELECT 1 FROM public.agent_evidence_events richer WHERE richer.session_id=e.session_id
        AND richer.stream_id=e.stream_id AND richer.generation=e.generation
        AND richer.event_type=e.event_type AND richer.call_id=e.call_id
        AND richer.turn_id IS NOT DISTINCT FROM e.turn_id AND richer.displayable
        AND (richer.content_length>e.content_length OR (richer.content_length=e.content_length
          AND richer.record_sequence<e.record_sequence)));
    UPDATE public.agent_evidence_sessions SET index_generation=index_generation+1 WHERE id=s.id;
    IF NOT p_complete THEN RETURN; END IF;
    UPDATE public.agent_evidence_objects SET indexed_parser_version=p_parser_version,parser_state=p_state
      WHERE session_id=s.id AND object_id=p_object_id AND indexed_parser_version<=p_parser_version;
    UPDATE public.agent_evidence_sessions SET
      event_count=(SELECT count(*) FROM public.agent_evidence_events WHERE session_id=s.id AND displayable AND NOT inherited),
      first_event_at=(SELECT min(event_at) FROM public.agent_evidence_events WHERE session_id=s.id AND displayable AND NOT inherited),
      last_event_at=(SELECT max(event_at) FROM public.agent_evidence_events WHERE session_id=s.id AND displayable AND NOT inherited),
      parser_version=GREATEST(parser_version,p_parser_version),
      indexed_revision=CASE WHEN NOT EXISTS(SELECT 1 FROM public.agent_evidence_objects
        WHERE session_id=s.id AND kind='segment' AND committed_revision IS NOT NULL
          AND indexed_parser_version<p_parser_version) THEN manifest_revision ELSE indexed_revision END,
      index_status=CASE WHEN NOT EXISTS(SELECT 1 FROM public.agent_evidence_objects
        WHERE session_id=s.id AND kind='segment' AND committed_revision IS NOT NULL
          AND indexed_parser_version<p_parser_version) THEN 'ready' ELSE 'pending' END WHERE id=s.id;
END $$;

CREATE OR REPLACE FUNCTION public.agent_evidence_days(
    p_user_id uuid,p_folder_id uuid,p_session_id uuid,p_timezone text,p_from date,p_to date)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
    SELECT COALESCE(jsonb_agg(day ORDER BY day->>'date'),'[]') FROM (
      SELECT jsonb_build_object('date',(e.event_at AT TIME ZONE p_timezone)::date,
          'event_count',count(*),'turn_count',count(DISTINCT e.turn_id),
          'first_event_id',(array_agg(e.event_id ORDER BY e.position))[1]) AS day
      FROM public.agent_evidence_events e JOIN public.agent_evidence_sessions s ON s.id=e.session_id
      WHERE e.user_id=p_user_id AND e.folder_id=p_folder_id AND e.session_id=p_session_id
        AND s.deleted_at IS NULL AND e.displayable AND NOT e.inherited
        AND (e.event_at AT TIME ZONE p_timezone)::date BETWEEN p_from AND p_to
      GROUP BY (e.event_at AT TIME ZONE p_timezone)::date
    ) days;
$$;

CREATE OR REPLACE FUNCTION public.delete_agent_evidence(p_user_id uuid,p_folder_id uuid,p_session_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE count_deleted integer;
BEGIN
    IF NOT EXISTS(SELECT 1 FROM public.agent_evidence_sessions
      WHERE id=p_session_id AND user_id=p_user_id AND folder_id=p_folder_id) THEN
        RAISE EXCEPTION 'evidence_not_found';
    END IF;
    WITH RECURSIVE tree AS (
      SELECT id FROM public.agent_evidence_sessions WHERE id=p_session_id
      UNION ALL SELECT child.id FROM public.agent_evidence_sessions child JOIN tree ON child.parent_session_id=tree.id
    ) UPDATE public.agent_evidence_sessions SET deleted_at=COALESCE(deleted_at,now()),
      capture_status='deleted',index_status='deleted' WHERE id IN(SELECT id FROM tree)
      AND user_id=p_user_id AND folder_id=p_folder_id;
    GET DIAGNOSTICS count_deleted = ROW_COUNT;
    RETURN jsonb_build_object('status','deleted','sessions',count_deleted);
END $$;

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['agent_evidence_sessions','agent_evidence_batches','agent_evidence_objects',
      'agent_evidence_events','agent_evidence_journal_links'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY owner_read ON public.%I FOR SELECT TO authenticated USING (user_id=auth.uid())',t);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon,authenticated',t);
    EXECUTE format('GRANT SELECT ON public.%I TO authenticated',t);
    EXECUTE format('GRANT ALL ON public.%I TO service_role',t);
  END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.prepare_agent_evidence(uuid,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.commit_agent_evidence(uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.publish_agent_evidence_index(uuid,text,jsonb,jsonb,integer,boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.delete_agent_evidence(uuid,uuid,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.agent_evidence_days(uuid,uuid,uuid,text,date,date) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_agent_evidence_upload(uuid,uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.finish_agent_evidence_upload(uuid,uuid,text,uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.expire_agent_evidence_batch(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.prepare_agent_evidence(uuid,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.commit_agent_evidence(uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.publish_agent_evidence_index(uuid,text,jsonb,jsonb,integer,boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.delete_agent_evidence(uuid,uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.agent_evidence_days(uuid,uuid,uuid,text,date,date) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_agent_evidence_upload(uuid,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.finish_agent_evidence_upload(uuid,uuid,text,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.expire_agent_evidence_batch(uuid) TO service_role;

-- Independent of owner/folder foreign keys: deletion must survive their cascade.
CREATE TABLE public.agent_evidence_purge_outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    storage_paths jsonb NOT NULL,
    not_before timestamptz NOT NULL DEFAULT now()+interval '15 minutes',
    created_at timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL DEFAULT 0
);
ALTER TABLE public.agent_evidence_purge_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.agent_evidence_purge_outbox FROM anon,authenticated;
GRANT ALL ON public.agent_evidence_purge_outbox TO service_role;
CREATE OR REPLACE FUNCTION public.archive_agent_evidence_purge_paths()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE paths jsonb; prefix text; node public.agent_evidence_sessions%ROWTYPE;
BEGIN
    SELECT COALESCE(jsonb_agg(storage_path),'[]') INTO paths
      FROM public.agent_evidence_objects WHERE session_id=OLD.id AND storage_path IS NOT NULL;
    prefix:=OLD.native_session_id; node:=OLD;
    WHILE node.parent_session_id IS NOT NULL LOOP
        SELECT * INTO node FROM public.agent_evidence_sessions WHERE id=node.parent_session_id;
        EXIT WHEN NOT FOUND;
        prefix:=node.native_session_id||'/subagents/'||prefix;
    END LOOP;
    prefix:=OLD.user_id::text||'/'||OLD.folder_id::text||'/'||OLD.agent||'/'||prefix;
    paths:=paths||jsonb_build_array(COALESCE(OLD.manifest_path,prefix||'/manifest.json'));
    INSERT INTO public.agent_evidence_purge_outbox(storage_paths) VALUES(paths);
    RETURN OLD;
END $$;
CREATE TRIGGER agent_evidence_purge_before_delete BEFORE DELETE ON public.agent_evidence_sessions
    FOR EACH ROW EXECUTE FUNCTION public.archive_agent_evidence_purge_paths();
REVOKE ALL ON FUNCTION public.archive_agent_evidence_purge_paths() FROM PUBLIC;
CREATE OR REPLACE FUNCTION public.archive_agent_evidence_object_purge_path()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
    IF OLD.storage_path IS NOT NULL THEN
        INSERT INTO public.agent_evidence_purge_outbox(storage_paths)
          VALUES(jsonb_build_array(OLD.storage_path));
    END IF;
    RETURN OLD;
END $$;
CREATE TRIGGER agent_evidence_object_purge_before_delete BEFORE DELETE ON public.agent_evidence_objects
    FOR EACH ROW EXECUTE FUNCTION public.archive_agent_evidence_object_purge_path();
REVOKE ALL ON FUNCTION public.archive_agent_evidence_object_purge_path() FROM PUBLIC;

-- Empty tool output is valid evidence; JSONL segments must remain nonempty.
ALTER TABLE public.agent_evidence_objects
    DROP CONSTRAINT agent_evidence_objects_byte_length_check;
ALTER TABLE public.agent_evidence_objects
    ADD CONSTRAINT agent_evidence_objects_byte_length_check
    CHECK (byte_length >= 0 AND byte_length <= 67108864
        AND (kind = 'attachment' OR byte_length > 0));

-- Supabase grants client roles EXECUTE explicitly; revoking PUBLIC is insufficient.
REVOKE ALL ON FUNCTION public.prepare_agent_evidence(uuid,jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.prepare_agent_evidence(uuid,jsonb) TO service_role;
REVOKE ALL ON FUNCTION public.commit_agent_evidence(uuid,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.commit_agent_evidence(uuid,text) TO service_role;
REVOKE ALL ON FUNCTION public.publish_agent_evidence_index(uuid,text,jsonb,jsonb,integer,boolean) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.publish_agent_evidence_index(uuid,text,jsonb,jsonb,integer,boolean) TO service_role;
REVOKE ALL ON FUNCTION public.delete_agent_evidence(uuid,uuid,uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.delete_agent_evidence(uuid,uuid,uuid) TO service_role;
REVOKE ALL ON FUNCTION public.agent_evidence_days(uuid,uuid,uuid,text,date,date) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.agent_evidence_days(uuid,uuid,uuid,text,date,date) TO service_role;
REVOKE ALL ON FUNCTION public.claim_agent_evidence_upload(uuid,uuid,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_agent_evidence_upload(uuid,uuid,text) TO service_role;
REVOKE ALL ON FUNCTION public.finish_agent_evidence_upload(uuid,uuid,text,uuid,text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.finish_agent_evidence_upload(uuid,uuid,text,uuid,text) TO service_role;
REVOKE ALL ON FUNCTION public.expire_agent_evidence_batch(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.expire_agent_evidence_batch(uuid) TO service_role;
REVOKE ALL ON FUNCTION public.archive_agent_evidence_purge_paths() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.archive_agent_evidence_purge_paths() TO service_role;
REVOKE ALL ON FUNCTION public.archive_agent_evidence_object_purge_path() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.archive_agent_evidence_object_purge_path() TO service_role;

-- Calendar activity is indexed native event time, rolled up to original root sessions.
CREATE INDEX agent_evidence_calendar_events ON public.agent_evidence_events
    (user_id, folder_id, event_at, session_id) WHERE displayable AND NOT inherited;

CREATE OR REPLACE FUNCTION public.agent_history_days(
    p_user_id uuid,p_folder_id uuid,p_from date,p_to date,p_timezone text,p_agent text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public AS $$
DECLARE result jsonb;
BEGIN
    IF p_to<p_from OR p_to-p_from>62 OR p_agent NOT IN ('codex','claude_code') THEN
        RAISE EXCEPTION 'evidence_invalid_calendar_range';
    END IF;
    WITH activity AS (
      SELECT (e.event_at AT TIME ZONE p_timezone)::date AS day,root.id AS root_id,root.agent
      FROM public.agent_evidence_events e
      JOIN public.agent_evidence_sessions source ON source.id=e.session_id
      JOIN public.agent_evidence_sessions root ON root.id=source.root_session_id
      WHERE e.user_id=p_user_id AND e.folder_id=p_folder_id
        AND source.user_id=p_user_id AND source.folder_id=p_folder_id AND source.deleted_at IS NULL
        AND root.user_id=p_user_id AND root.folder_id=p_folder_id AND root.deleted_at IS NULL
        AND root.parent_session_id IS NULL AND (p_agent IS NULL OR root.agent=p_agent)
        AND e.displayable AND NOT e.inherited
        AND e.event_at >= p_from::timestamp AT TIME ZONE p_timezone
        AND e.event_at < (p_to+1)::timestamp AT TIME ZONE p_timezone
    ), daily AS (
      SELECT day,count(DISTINCT root_id) AS session_count,count(*) AS event_count,
        array_agg(DISTINCT agent ORDER BY agent) AS agents FROM activity GROUP BY day
    ) SELECT COALESCE(jsonb_agg(jsonb_build_object('date',day,'session_count',session_count,
        'event_count',event_count,'agents',agents) ORDER BY day),'[]') INTO result FROM daily;
    RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.agent_history_sessions(
    p_user_id uuid,p_folder_id uuid,p_date date,p_timezone text,p_limit integer,
    p_before_at timestamptz DEFAULT NULL,p_before_id uuid DEFAULT NULL,p_agent text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public AS $$
DECLARE result jsonb;
BEGIN
    IF p_limit<1 OR p_limit>101 OR p_agent NOT IN ('codex','claude_code') THEN
        RAISE EXCEPTION 'evidence_invalid_calendar_range';
    END IF;
    WITH activity AS (
      SELECT root.id AS root_id,e.event_at,e.event_id,e.session_id,e.position
      FROM public.agent_evidence_events e
      JOIN public.agent_evidence_sessions source ON source.id=e.session_id
      JOIN public.agent_evidence_sessions root ON root.id=source.root_session_id
      WHERE e.user_id=p_user_id AND e.folder_id=p_folder_id
        AND source.user_id=p_user_id AND source.folder_id=p_folder_id AND source.deleted_at IS NULL
        AND root.user_id=p_user_id AND root.folder_id=p_folder_id AND root.deleted_at IS NULL
        AND root.parent_session_id IS NULL AND (p_agent IS NULL OR root.agent=p_agent)
        AND e.displayable AND NOT e.inherited
        AND e.event_at >= p_date::timestamp AT TIME ZONE p_timezone
        AND e.event_at < (p_date+1)::timestamp AT TIME ZONE p_timezone
    ), daily AS (
      SELECT root_id,min(event_at) AS first_at,max(event_at) AS last_at,count(*) AS event_count,
        (array_agg(event_id ORDER BY event_at,position,event_id))[1] AS first_event_id,
        (array_agg(session_id ORDER BY event_at,position,event_id))[1] AS first_session_id
      FROM activity GROUP BY root_id
    ), page AS (
      SELECT * FROM daily WHERE p_before_at IS NULL OR (last_at,root_id)<(p_before_at,p_before_id)
      ORDER BY last_at DESC,root_id DESC LIMIT p_limit
    ), children AS (
      SELECT child.parent_session_id,jsonb_agg(jsonb_build_object('id',child.id,'agent',child.agent,
        'native_session_id',child.native_session_id,'event_count',child.event_count) ORDER BY child.id) AS items
      FROM public.agent_evidence_sessions child JOIN page ON child.parent_session_id=page.root_id
      WHERE child.user_id=p_user_id AND child.folder_id=p_folder_id AND child.deleted_at IS NULL
      GROUP BY child.parent_session_id
    ) SELECT COALESCE(jsonb_agg(jsonb_build_object(
      'id',root.id,'agent',root.agent,'native_session_id',root.native_session_id,
      'parent_session_id',root.parent_session_id,'root_session_id',root.root_session_id,
      'title',NULL,'summary',NULL,'first_event_at',root.first_event_at,'last_event_at',root.last_event_at,
      'manifest_revision',root.manifest_revision,'indexed_revision',root.indexed_revision,
      'capture_status',root.capture_status,'index_status',root.index_status,'event_count',root.event_count,
      'gaps',root.gaps,'children',COALESCE(children.items,'[]'),
      'day_first_event_at',page.first_at,'day_last_event_at',page.last_at,
      'day_event_count',page.event_count,'day_first_event_id',page.first_event_id,
      'day_first_session_id',page.first_session_id) ORDER BY page.last_at DESC,page.root_id DESC),'[]')
      INTO result FROM page JOIN public.agent_evidence_sessions root ON root.id=page.root_id
      LEFT JOIN children ON children.parent_session_id=root.id;
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.agent_history_days(uuid,uuid,date,date,text,text) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.agent_history_sessions(uuid,uuid,date,text,integer,timestamptz,uuid,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.agent_history_days(uuid,uuid,date,date,text,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.agent_history_sessions(uuid,uuid,date,text,integer,timestamptz,uuid,text) TO service_role;

-- Bound session child metadata and avoid accumulating every anchor ID in arrays.
CREATE OR REPLACE FUNCTION public.agent_history_sessions(
    p_user_id uuid,p_folder_id uuid,p_date date,p_timezone text,p_limit integer,
    p_before_at timestamptz DEFAULT NULL,p_before_id uuid DEFAULT NULL,p_agent text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=public AS $$
DECLARE result jsonb;
BEGIN
    IF p_limit<1 OR p_limit>101 OR p_agent NOT IN ('codex','claude_code') THEN
        RAISE EXCEPTION 'evidence_invalid_calendar_range';
    END IF;
    WITH activity AS (
      SELECT root.id AS root_id,e.event_at,e.event_id,e.session_id,e.position
      FROM public.agent_evidence_events e
      JOIN public.agent_evidence_sessions source ON source.id=e.session_id
      JOIN public.agent_evidence_sessions root ON root.id=source.root_session_id
      WHERE e.user_id=p_user_id AND e.folder_id=p_folder_id
        AND source.user_id=p_user_id AND source.folder_id=p_folder_id AND source.deleted_at IS NULL
        AND root.user_id=p_user_id AND root.folder_id=p_folder_id AND root.deleted_at IS NULL
        AND root.parent_session_id IS NULL AND (p_agent IS NULL OR root.agent=p_agent)
        AND e.displayable AND NOT e.inherited
        AND e.event_at >= p_date::timestamp AT TIME ZONE p_timezone
        AND e.event_at < (p_date+1)::timestamp AT TIME ZONE p_timezone
    ), daily AS (
      SELECT root_id,min(event_at) AS first_at,max(event_at) AS last_at,count(*) AS event_count
      FROM activity GROUP BY root_id
    ), first_activity AS (
      SELECT DISTINCT ON (root_id) root_id,event_id AS first_event_id,session_id AS first_session_id
      FROM activity ORDER BY root_id,event_at,position,event_id
    ), page AS (
      SELECT daily.*,first_activity.first_event_id,first_activity.first_session_id
      FROM daily JOIN first_activity USING(root_id)
      WHERE p_before_at IS NULL OR (last_at,root_id)<(p_before_at,p_before_id)
      ORDER BY last_at DESC,root_id DESC LIMIT p_limit
    ), child_candidates AS (
      SELECT child.*,row_number() OVER(PARTITION BY child.parent_session_id ORDER BY child.id) AS child_rank
      FROM public.agent_evidence_sessions child JOIN page ON child.parent_session_id=page.root_id
      WHERE child.user_id=p_user_id AND child.folder_id=p_folder_id AND child.deleted_at IS NULL
    ), children AS (
      SELECT child.parent_session_id,jsonb_agg(jsonb_build_object('id',child.id,'agent',child.agent,
        'native_session_id',child.native_session_id,'event_count',child.event_count) ORDER BY child.id) AS items
      FROM child_candidates child WHERE child.child_rank<=100 GROUP BY child.parent_session_id
    ) SELECT COALESCE(jsonb_agg(jsonb_build_object(
      'id',root.id,'agent',root.agent,'native_session_id',root.native_session_id,
      'parent_session_id',root.parent_session_id,'root_session_id',root.root_session_id,
      'title',NULL,'summary',NULL,'first_event_at',root.first_event_at,'last_event_at',root.last_event_at,
      'manifest_revision',root.manifest_revision,'indexed_revision',root.indexed_revision,
      'capture_status',root.capture_status,'index_status',root.index_status,'event_count',root.event_count,
      'gaps',root.gaps,'children',COALESCE(children.items,'[]'),
      'day_first_event_at',page.first_at,'day_last_event_at',page.last_at,
      'day_event_count',page.event_count,'day_first_event_id',page.first_event_id,
      'day_first_session_id',page.first_session_id) ORDER BY page.last_at DESC,page.root_id DESC),'[]')
      INTO result FROM page JOIN public.agent_evidence_sessions root ON root.id=page.root_id
      LEFT JOIN children ON children.parent_session_id=root.id;
    RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.agent_history_sessions(uuid,uuid,date,text,integer,timestamptz,uuid,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.agent_history_sessions(uuid,uuid,date,text,integer,timestamptz,uuid,text) TO service_role;

-- Searchable journal projection. Native originals remain in their existing archive.
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA extensions;
CREATE TABLE public.agent_journal_search_entries (
 user_id uuid NOT NULL, folder_id uuid NOT NULL, journal_date date NOT NULL,
 entry_id text NOT NULL, agent text NOT NULL CHECK(agent IN ('codex','claude_code')),
 session_id text NOT NULL, captured_at timestamptz NOT NULL,
 title text NOT NULL DEFAULT '', summary text NOT NULL DEFAULT '', body text NOT NULL,
 PRIMARY KEY(user_id,folder_id,journal_date,entry_id),
 FOREIGN KEY(user_id,folder_id,journal_date) REFERENCES public.agent_journal_days(user_id,folder_id,journal_date) ON DELETE CASCADE
);
CREATE INDEX agent_journal_search_scope ON public.agent_journal_search_entries(user_id,folder_id,agent,session_id,captured_at DESC);
CREATE INDEX agent_journal_search_body ON public.agent_journal_search_entries USING gin(body extensions.gin_trgm_ops);
CREATE INDEX agent_journal_search_title ON public.agent_journal_search_entries USING gin(title extensions.gin_trgm_ops);
CREATE INDEX agent_journal_search_summary ON public.agent_journal_search_entries USING gin(summary extensions.gin_trgm_ops);
ALTER TABLE public.agent_journal_days ADD COLUMN search_sha256 text;
ALTER TABLE public.agent_journal_search_entries ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Read own journal search entries" ON public.agent_journal_search_entries FOR SELECT USING(auth.uid()=user_id);
REVOKE ALL ON public.agent_journal_search_entries FROM PUBLIC,anon,authenticated;
GRANT SELECT ON public.agent_journal_search_entries TO authenticated;
GRANT ALL ON public.agent_journal_search_entries TO service_role;

CREATE FUNCTION public.index_agent_journal(p_user_id uuid,p_folder_id uuid,p_date date,p_sha256 text,p_entries jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE d public.agent_journal_days%ROWTYPE;
BEGIN
 SELECT * INTO d FROM public.agent_journal_days WHERE user_id=p_user_id AND folder_id=p_folder_id AND journal_date=p_date FOR UPDATE;
 IF NOT FOUND OR d.content_sha256<>p_sha256 THEN RETURN false; END IF;
 IF d.search_sha256=p_sha256 THEN RETURN true; END IF;
 IF jsonb_typeof(p_entries)<>'array' OR jsonb_array_length(p_entries)<>d.entry_count THEN RAISE EXCEPTION 'Search entry count mismatch'; END IF;
 DELETE FROM public.agent_journal_search_entries WHERE user_id=p_user_id AND folder_id=p_folder_id AND journal_date=p_date;
 INSERT INTO public.agent_journal_search_entries(user_id,folder_id,journal_date,entry_id,agent,session_id,captured_at,title,summary,body)
 SELECT p_user_id,p_folder_id,p_date,x.entry_id,x.agent,x.session_id,x.captured_at,coalesce(x.title,''),coalesce(x.summary,''),x.body
 FROM jsonb_to_recordset(p_entries) AS x(entry_id text,agent text,session_id text,captured_at timestamptz,title text,summary text,body text);
 UPDATE public.agent_journal_days SET search_sha256=p_sha256 WHERE user_id=p_user_id AND folder_id=p_folder_id AND journal_date=p_date;
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.index_agent_journal(uuid,uuid,date,text,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.index_agent_journal(uuid,uuid,date,text,jsonb) TO service_role;

CREATE FUNCTION public.publish_searchable_agent_journal(
 p_user_id uuid,p_folder_id uuid,p_date date,p_expected_revision bigint,p_storage_path text,p_sha256 text,
 p_entry_count integer,p_agents text[],p_first_entry_at timestamptz,p_last_entry_at timestamptz,p_entries jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE result jsonb;
BEGIN
 result:=public.publish_agent_journal(p_user_id,p_folder_id,p_date,p_expected_revision,p_storage_path,p_sha256,p_entry_count,p_agents,p_first_entry_at,p_last_entry_at);
 IF result->>'status' IN ('ok','unchanged') THEN
  PERFORM public.index_agent_journal(p_user_id,p_folder_id,p_date,p_sha256,p_entries);
 END IF;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.publish_searchable_agent_journal(uuid,uuid,date,bigint,text,text,integer,text[],timestamptz,timestamptz,jsonb) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.publish_searchable_agent_journal(uuid,uuid,date,bigint,text,text,integer,text[],timestamptz,timestamptz,jsonb) TO service_role;

-- Pattern is a restricted, validated expression generated by the API, never SQL text.
CREATE FUNCTION public.search_agent_history(p_user_id uuid,p_folder_id uuid,p_pattern text DEFAULT '',p_fields text DEFAULT 'all',p_first date DEFAULT NULL,p_last date DEFAULT NULL,p_agent text DEFAULT NULL,p_session text DEFAULT NULL,p_timezone text DEFAULT 'UTC',p_limit integer DEFAULT 20,p_offset integer DEFAULT 0,p_snippet text DEFAULT NULL)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public SET statement_timeout='3s' AS $$
WITH latest AS MATERIALIZED (
 SELECT DISTINCT ON(agent,session_id) agent,session_id,title,summary
 FROM public.agent_journal_search_entries e WHERE user_id=p_user_id AND folder_id=p_folder_id
 AND EXISTS (SELECT 1 FROM public.agent_journal_days d WHERE d.user_id=e.user_id AND d.folder_id=e.folder_id AND d.journal_date=e.journal_date AND d.search_sha256=d.content_sha256)
 ORDER BY agent,session_id,captured_at DESC,entry_id DESC
), candidates AS MATERIALIZED (
 SELECT DISTINCT agent,session_id FROM public.agent_journal_search_entries
 WHERE user_id=p_user_id AND folder_id=p_folder_id AND
 (p_pattern='' OR title ~* p_pattern OR (p_fields='all' AND (summary ~* p_pattern OR body ~* p_pattern)))
), scoped AS MATERIALIZED (
 SELECT e.*,l.title AS current_title,l.summary AS current_summary,
 (e.captured_at AT TIME ZONE p_timezone)::date AS local_date,
 p_pattern<>'' AND l.title ~* p_pattern AS title_hit,
 p_pattern<>'' AND p_fields='all' AND l.summary ~* p_pattern AS overview_hit,
 p_pattern<>'' AND p_fields='all' AND e.body ~* p_pattern AS body_hit
 FROM public.agent_journal_search_entries e JOIN latest l USING(agent,session_id) JOIN candidates c USING(agent,session_id)
 WHERE user_id=p_user_id AND folder_id=p_folder_id
 AND EXISTS (SELECT 1 FROM public.agent_journal_days d WHERE d.user_id=e.user_id AND d.folder_id=e.folder_id AND d.journal_date=e.journal_date AND d.search_sha256=d.content_sha256)
 AND (p_agent IS NULL OR e.agent=p_agent) AND (p_session IS NULL OR starts_with(e.session_id,p_session))
 AND (p_first IS NULL OR e.captured_at >= p_first::timestamp AT TIME ZONE p_timezone)
 AND (p_last IS NULL OR e.captured_at < (p_last+1)::timestamp AT TIME ZONE p_timezone)
), ranked AS (
 SELECT *,row_number() OVER(PARTITION BY agent,session_id,body_hit ORDER BY captured_at DESC,entry_id) AS match_rank FROM scoped
), grouped AS (
 SELECT agent,session_id,max(current_title) title,max(current_summary) summary,
 bool_or(title_hit) title_match,bool_or(overview_hit) overview_match,
 count(*) entry_count,count(*) FILTER(WHERE body_hit) matching_entry_count,
 array_agg(DISTINCT local_date ORDER BY local_date) dates,
 array_agg(DISTINCT local_date ORDER BY local_date) FILTER(WHERE body_hit) matching_dates,
 max(captured_at) last_at,
 coalesce(jsonb_agg(jsonb_build_object('id',entry_id,'date',local_date,'captured_at',captured_at,
 'excerpt',substring(body FROM greatest(1,coalesce(nullif(strpos(lower(body),lower(coalesce(p_snippet,substring(body from p_pattern)))),0),1)-100) FOR 500)) ORDER BY captured_at DESC,entry_id) FILTER(WHERE body_hit AND match_rank<=5),'[]') matches
 FROM ranked GROUP BY agent,session_id
 HAVING p_pattern='' OR bool_or(title_hit OR overview_hit OR body_hit)
), page AS (SELECT * FROM grouped ORDER BY last_at DESC,agent,session_id LIMIT greatest(1,least(p_limit,50)) OFFSET greatest(0,least(p_offset,10000)))
SELECT jsonb_build_object('sessions',coalesce((SELECT jsonb_agg(to_jsonb(page) ORDER BY last_at DESC,agent,session_id) FROM page),'[]'),
 'total_sessions',(SELECT count(*) FROM grouped),'total_entries',(SELECT coalesce(sum(matching_entry_count),0) FROM grouped),
 'has_more',(SELECT count(*) FROM grouped)>p_offset+p_limit,
 'coverage',jsonb_build_object('indexed_days',(SELECT count(*) FROM public.agent_journal_days WHERE user_id=p_user_id AND folder_id=p_folder_id AND search_sha256=content_sha256),
 'pending_days',(SELECT count(*) FROM public.agent_journal_days WHERE user_id=p_user_id AND folder_id=p_folder_id AND search_sha256 IS DISTINCT FROM content_sha256)))
$$;
REVOKE ALL ON FUNCTION public.search_agent_history(uuid,uuid,text,text,date,date,text,text,text,integer,integer,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.search_agent_history(uuid,uuid,text,text,date,date,text,text,text,integer,integer,text) TO service_role;

CREATE FUNCTION public.pending_agent_journal_search(p_user_id uuid,p_folder_id uuid,p_limit integer DEFAULT 10)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
 SELECT jsonb_build_object('remaining_days',count(*),'days',coalesce((SELECT jsonb_agg(x) FROM
 (SELECT journal_date,content_sha256 FROM public.agent_journal_days WHERE user_id=p_user_id AND folder_id=p_folder_id
 AND search_sha256 IS DISTINCT FROM content_sha256 ORDER BY journal_date LIMIT greatest(1,least(p_limit,20))) x),'[]'))
 FROM public.agent_journal_days WHERE user_id=p_user_id AND folder_id=p_folder_id AND search_sha256 IS DISTINCT FROM content_sha256
$$;
REVOKE ALL ON FUNCTION public.pending_agent_journal_search(uuid,uuid,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.pending_agent_journal_search(uuid,uuid,integer) TO service_role;

-- Rebuildable lexical projections. Original bodies remain in private Storage.
ALTER TABLE public.agent_evidence_objects ADD COLUMN memory_index_version integer NOT NULL DEFAULT 0;
CREATE TABLE public.agent_memory_chunks (
 session_id uuid NOT NULL, event_id text NOT NULL, object_id text NOT NULL,
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
 char_start integer NOT NULL CHECK(char_start>=0), char_length integer NOT NULL CHECK(char_length BETWEEN 1 AND 2000),
 lexemes tsvector NOT NULL,
 PRIMARY KEY(session_id,event_id,char_start),
 FOREIGN KEY(session_id,event_id) REFERENCES public.agent_evidence_events(session_id,event_id) ON DELETE CASCADE
);
CREATE INDEX agent_memory_lexical ON public.agent_memory_chunks USING gin(lexemes);
CREATE INDEX agent_memory_scope ON public.agent_memory_chunks(user_id,folder_id,session_id);
ALTER TABLE public.agent_memory_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY owner_read ON public.agent_memory_chunks FOR SELECT TO authenticated USING(user_id=auth.uid());
GRANT SELECT ON public.agent_memory_chunks TO authenticated;
GRANT ALL ON public.agent_memory_chunks TO service_role;

CREATE OR REPLACE FUNCTION public.publish_agent_memory_index(p_session_id uuid,p_object_id text,p_chunks jsonb,p_reset boolean DEFAULT false,p_complete boolean DEFAULT true)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE s public.agent_evidence_sessions%ROWTYPE; c jsonb; normalized text;
BEGIN
 SELECT * INTO s FROM public.agent_evidence_sessions WHERE id=p_session_id FOR UPDATE;
 IF NOT FOUND OR s.deleted_at IS NOT NULL THEN RETURN; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.agent_evidence_objects WHERE session_id=s.id AND object_id=p_object_id AND committed_revision IS NOT NULL AND indexed_parser_version>=1) THEN RAISE EXCEPTION 'evidence_not_indexed'; END IF;
 IF jsonb_array_length(p_chunks)>500 THEN RAISE EXCEPTION 'memory_batch_too_large'; END IF;
 IF p_reset THEN
  UPDATE public.agent_evidence_objects SET memory_index_version=0 WHERE session_id=s.id AND object_id=p_object_id;
  DELETE FROM public.agent_memory_chunks WHERE session_id=s.id AND object_id=p_object_id;
 END IF;
 FOR c IN SELECT * FROM jsonb_array_elements(p_chunks) LOOP
  IF length(c->>'text')<>(c->>'char_length')::integer THEN RAISE EXCEPTION 'invalid_memory_span'; END IF;
  normalized := replace(replace(replace(c->>'text',chr(92)||'n',' '),chr(92)||'r',' '),chr(92)||'t',' ');
  INSERT INTO public.agent_memory_chunks(session_id,event_id,object_id,user_id,folder_id,char_start,char_length,lexemes)
   SELECT s.id,e.event_id,p_object_id,s.user_id,s.folder_id,(c->>'char_start')::integer,(c->>'char_length')::integer,
     to_tsvector('simple',c->>'text')||to_tsvector('english',c->>'text')
     || CASE WHEN normalized<>c->>'text' THEN to_tsvector('simple',normalized)||to_tsvector('english',normalized) ELSE ''::tsvector END
   FROM public.agent_evidence_events e WHERE e.session_id=s.id AND e.object_id=p_object_id AND e.event_id=c->>'event_id' AND e.displayable AND NOT e.inherited
  ON CONFLICT(session_id,event_id,char_start) DO UPDATE SET lexemes=excluded.lexemes,char_length=excluded.char_length;
 END LOOP;
 IF p_complete THEN UPDATE public.agent_evidence_objects SET memory_index_version=2 WHERE session_id=s.id AND object_id=p_object_id; END IF;
END $$;

CREATE FUNCTION public.search_agent_memory(p_user_id uuid,p_folder_ids uuid[],p_terms text[],p_after timestamptz DEFAULT NULL,p_before timestamptz DEFAULT NULL,p_session text DEFAULT NULL,p_order text DEFAULT 'chronological',p_limit integer DEFAULT 50,p_offset integer DEFAULT 0)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public SET statement_timeout='5s' AS $$
WITH query AS (
 SELECT CASE WHEN cardinality(p_terms)>0 THEN array_to_string(ARRAY(SELECT '('||plainto_tsquery('simple',t)::text||CASE WHEN plainto_tsquery('english',t)::text<>'' THEN ' | '||plainto_tsquery('english',t)::text ELSE '' END||')' FROM unnest(p_terms) t WHERE length(t)>0),' | ')::tsquery END q
), matched AS MATERIALIZED (
 SELECT c.session_id,c.event_id,c.object_id,c.char_start,c.char_length,c.folder_id,
 e.event_at,e.role,e.event_type,e.record_sequence,e.call_id,e.source_truncated,
 s.native_session_id,s.agent,s.manifest_revision,s.indexed_revision,
 CASE WHEN query.q IS NULL THEN 0 ELSE ts_rank_cd(c.lexemes,query.q) END relevance,
 row_number() OVER(PARTITION BY c.session_id,c.event_id ORDER BY CASE WHEN query.q IS NULL THEN 0 ELSE ts_rank_cd(c.lexemes,query.q) END DESC,c.char_start) chunk_rank
 FROM public.agent_memory_chunks c
 JOIN public.agent_evidence_events e USING(session_id,event_id)
 JOIN public.agent_evidence_sessions s ON s.id=c.session_id
 JOIN public.agent_evidence_objects o ON o.session_id=c.session_id AND o.object_id=c.object_id CROSS JOIN query
 WHERE c.user_id=p_user_id AND c.folder_id=ANY(p_folder_ids) AND e.user_id=p_user_id AND s.user_id=p_user_id
 AND s.deleted_at IS NULL AND e.displayable AND NOT e.inherited AND o.memory_index_version>=1
 AND o.committed_revision IS NOT NULL AND (query.q IS NULL OR c.lexemes@@query.q)
 AND (p_after IS NULL OR e.event_at>=p_after) AND (p_before IS NULL OR e.event_at<p_before)
 AND (p_session IS NULL OR starts_with(s.native_session_id,p_session) OR s.id::text=p_session)
), events AS MATERIALIZED(SELECT * FROM matched WHERE chunk_rank=1),
ranked AS (SELECT *,row_number() OVER(PARTITION BY folder_id,(event_at AT TIME ZONE 'UTC')::date ORDER BY relevance DESC,event_at DESC NULLS LAST,event_id) temporal_rank FROM events),
page AS (SELECT * FROM ranked ORDER BY
 CASE WHEN p_order='chronological' AND cardinality(p_terms)>0 THEN temporal_rank END ASC,
 CASE WHEN p_order='relevance' OR (p_order='chronological' AND cardinality(p_terms)>0) THEN relevance END DESC,
 CASE WHEN p_order='latest' THEN event_at END DESC NULLS LAST,
 CASE WHEN p_order<>'latest' THEN event_at END ASC NULLS LAST,session_id,record_sequence
 LIMIT greatest(1,least(p_limit,50)) OFFSET greatest(0,least(p_offset,10000)))
SELECT jsonb_build_object('matches',coalesce((SELECT jsonb_agg(to_jsonb(page)||jsonb_build_object('content_preview',e.content_preview)) FROM page JOIN public.agent_evidence_events e USING(session_id,event_id)),'[]'),
 'total_matches',(SELECT count(*) FROM events),
 'has_more',(SELECT count(*) FROM events)>p_offset+p_limit,
 'index_pending_objects',(SELECT count(*) FROM public.agent_evidence_objects o JOIN public.agent_evidence_sessions s ON s.id=o.session_id WHERE o.user_id=p_user_id AND o.folder_id=ANY(p_folder_ids) AND s.deleted_at IS NULL AND o.kind='segment' AND o.committed_revision IS NOT NULL AND o.memory_index_version<2))
$$;
REVOKE ALL ON FUNCTION public.publish_agent_memory_index(uuid,text,jsonb,boolean,boolean) FROM PUBLIC,anon,authenticated;
REVOKE ALL ON FUNCTION public.search_agent_memory(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.publish_agent_memory_index(uuid,text,jsonb,boolean,boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.search_agent_memory(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer) TO service_role;

-- Keep latest strictly temporal within the explicit-identifier candidate set.
-- Additive RPC: old backends keep their existing search contract during rollout.
CREATE OR REPLACE FUNCTION public.search_agent_memory_v2(
 p_user_id uuid,p_folder_ids uuid[],p_terms text[],
 p_after timestamptz DEFAULT NULL,p_before timestamptz DEFAULT NULL,
 p_session text DEFAULT NULL,p_order text DEFAULT 'chronological',
 p_limit integer DEFAULT 50,p_offset integer DEFAULT 0,
 p_identifiers text[] DEFAULT '{}',p_timezone text DEFAULT 'UTC'
)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public
SET statement_timeout='5s' AS $$
WITH terms AS MATERIALIZED (
 SELECT DISTINCT lower(t) term,
  ('('||plainto_tsquery('simple',t)::text||
    CASE WHEN plainto_tsquery('english',t)::text<>''
    THEN ' | '||plainto_tsquery('english',t)::text ELSE '' END||')')::tsquery q
 FROM unnest(p_terms) t WHERE length(t)>0
), query AS (
 SELECT CASE WHEN count(*)>0 THEN string_agg('('||q::text||')',' | ')::tsquery END q
 FROM terms
), matched AS MATERIALIZED (
 SELECT c.session_id,c.event_id,c.object_id,c.char_start,c.char_length,c.folder_id,
 e.event_at,e.role,e.event_type,e.record_sequence,e.call_id,e.source_truncated,
 s.native_session_id,s.agent,s.manifest_revision,s.indexed_revision,
 ARRAY(SELECT t.term FROM terms t WHERE c.lexemes@@t.q) matched_terms,
 (SELECT count(*) FROM terms t WHERE c.lexemes@@t.q)
 + (SELECT coalesce(sum(CASE WHEN length(t.term)>=5 OR t.term~'[_0-9]'
     THEN 100 ELSE 0.25 END),0) FROM terms t
     WHERE t.term=ANY(p_identifiers) AND c.lexemes@@t.q)
 + CASE WHEN query.q IS NULL THEN 0 ELSE ts_rank_cd(c.lexemes,query.q,32) END relevance
 FROM public.agent_memory_chunks c
 JOIN public.agent_evidence_events e USING(session_id,event_id)
 JOIN public.agent_evidence_sessions s ON s.id=c.session_id
 JOIN public.agent_evidence_objects o ON o.session_id=c.session_id AND o.object_id=c.object_id
 CROSS JOIN query
 WHERE c.user_id=p_user_id AND c.folder_id=ANY(p_folder_ids)
 AND e.user_id=p_user_id AND s.user_id=p_user_id AND s.deleted_at IS NULL
 AND e.displayable AND NOT e.inherited AND o.memory_index_version>=1
 AND o.committed_revision IS NOT NULL AND (query.q IS NULL OR c.lexemes@@query.q)
 AND (p_after IS NULL OR e.event_at>=p_after) AND (p_before IS NULL OR e.event_at<p_before)
 AND (p_session IS NULL OR starts_with(s.native_session_id,p_session) OR s.id::text=p_session)
), focused AS MATERIALIZED (
 SELECT * FROM matched m WHERE
 NOT EXISTS (SELECT 1 FROM matched x WHERE EXISTS (
  SELECT 1 FROM unnest(x.matched_terms) t
  WHERE t=ANY(p_identifiers) AND (length(t)>=5 OR t~'[_0-9]')))
 OR EXISTS (SELECT 1 FROM unnest(m.matched_terms) t
  WHERE t=ANY(p_identifiers) AND (length(t)>=5 OR t~'[_0-9]'))
), events AS MATERIALIZED (
 SELECT DISTINCT ON(session_id,event_id) * FROM focused
 ORDER BY session_id,event_id,relevance DESC,char_start
), ranked AS (
 SELECT *,row_number() OVER(
  PARTITION BY folder_id,(event_at AT TIME ZONE p_timezone)::date
  ORDER BY relevance DESC,event_at DESC NULLS LAST,event_id) temporal_rank
 FROM events
), page AS (
 SELECT * FROM ranked ORDER BY
 CASE WHEN p_order='chronological' AND cardinality(p_terms)>0 THEN temporal_rank END ASC,
 CASE WHEN p_order='relevance' OR (p_order='chronological' AND cardinality(p_terms)>0) THEN relevance END DESC,
 CASE WHEN p_order='latest' THEN event_at END DESC NULLS LAST,
 CASE WHEN p_order<>'latest' THEN event_at END ASC NULLS LAST,session_id,record_sequence
 LIMIT greatest(1,least(p_limit,50)) OFFSET greatest(0,least(p_offset,10000))
)
SELECT jsonb_build_object(
 'matches',coalesce((SELECT jsonb_agg(to_jsonb(page)||jsonb_build_object('content_preview',e.content_preview))
  FROM page JOIN public.agent_evidence_events e USING(session_id,event_id)),'[]'),
 'total_matches',(SELECT count(*) FROM events),
 'has_more',(SELECT count(*) FROM events)>p_offset+p_limit,
 'unmatched_identifiers',coalesce((SELECT jsonb_agg(i) FROM unnest(p_identifiers) i
  WHERE NOT EXISTS(SELECT 1 FROM events e WHERE i=ANY(e.matched_terms))),'[]'),
 'index_pending_objects',(SELECT count(*) FROM public.agent_evidence_objects o
  JOIN public.agent_evidence_sessions s ON s.id=o.session_id
  WHERE o.user_id=p_user_id AND o.folder_id=ANY(p_folder_ids) AND s.deleted_at IS NULL
  AND o.kind='segment' AND o.committed_revision IS NOT NULL AND o.memory_index_version<2)
)
$$;
REVOKE ALL ON FUNCTION public.search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text) TO service_role;
-- A single owner-scoped statement snapshot; never reads transcript Storage objects.
BEGIN;
CREATE OR REPLACE FUNCTION public.agent_memory_overview(
 p_user_id uuid,p_folder_ids uuid[],p_after timestamptz DEFAULT NULL,
 p_before timestamptz DEFAULT NULL,p_session text DEFAULT NULL,p_timezone text DEFAULT 'UTC'
) RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=public,pg_temp SET statement_timeout='5s' AS $$
WITH folders AS MATERIALIZED (
 SELECT id FROM public.folders WHERE user_id=p_user_id AND id=ANY(p_folder_ids)
), journals AS MATERIALIZED (
 SELECT j.folder_id,j.session_id,j.agent,j.title,j.body,j.captured_at,j.entry_id
 FROM public.agent_journal_search_entries j JOIN folders f ON f.id=j.folder_id
 WHERE j.user_id=p_user_id AND (p_after IS NULL OR j.captured_at>=p_after)
 AND (p_before IS NULL OR j.captured_at<p_before)
 AND (p_session IS NULL OR starts_with(j.session_id,p_session))
), originals AS MATERIALIZED (
 SELECT e.folder_id,s.id AS session_id,s.native_session_id,s.agent,
 (e.event_at AT TIME ZONE p_timezone)::date AS date,count(*) AS event_count
 FROM public.agent_evidence_events e
 JOIN folders f ON f.id=e.folder_id
 JOIN public.agent_evidence_sessions s ON s.id=e.session_id
 JOIN public.agent_evidence_objects o ON o.session_id=e.session_id AND o.object_id=e.object_id
 WHERE e.user_id=p_user_id AND s.user_id=p_user_id AND s.folder_id=e.folder_id
 AND s.deleted_at IS NULL AND e.displayable AND NOT e.inherited
 AND o.committed_revision IS NOT NULL
 AND (p_after IS NULL OR e.event_at>=p_after) AND (p_before IS NULL OR e.event_at<p_before)
 AND (p_session IS NULL OR starts_with(s.native_session_id,p_session) OR s.id::text=p_session)
 GROUP BY e.folder_id,s.id,s.native_session_id,s.agent,(e.event_at AT TIME ZONE p_timezone)::date
)
SELECT jsonb_build_object(
 'snapshot_at',statement_timestamp(),
 'entry_count',(SELECT count(*) FROM journals),
 'original_day_count',(SELECT count(*) FROM originals),
 'entries',coalesce((SELECT jsonb_agg(to_jsonb(j) ORDER BY captured_at,entry_id)
 FROM (SELECT * FROM journals ORDER BY captured_at,entry_id LIMIT 2000) j),'[]'),
 'original_days',coalesce((SELECT jsonb_agg(to_jsonb(o) ORDER BY date,folder_id,session_id)
 FROM (SELECT * FROM originals ORDER BY date,folder_id,session_id LIMIT 2000) o),'[]')
)
$$;
REVOKE ALL ON FUNCTION public.agent_memory_overview(uuid,uuid[],timestamptz,timestamptz,text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.agent_memory_overview(uuid,uuid[],timestamptz,timestamptz,text,text) TO service_role;
COMMIT;

-- Do not call an original activity inventory complete while captured segments await parsing.
BEGIN;
CREATE OR REPLACE FUNCTION public.agent_memory_overview(
 p_user_id uuid,p_folder_ids uuid[],p_after timestamptz DEFAULT NULL,
 p_before timestamptz DEFAULT NULL,p_session text DEFAULT NULL,p_timezone text DEFAULT 'UTC'
) RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=public,pg_temp SET statement_timeout='5s' AS $$
WITH folders AS MATERIALIZED (
 SELECT id FROM public.folders WHERE user_id=p_user_id AND id=ANY(p_folder_ids)
), journals AS MATERIALIZED (
 SELECT j.folder_id,j.session_id,j.agent,j.title,j.body,j.captured_at,j.entry_id
 FROM public.agent_journal_search_entries j JOIN folders f ON f.id=j.folder_id
 WHERE j.user_id=p_user_id AND (p_after IS NULL OR j.captured_at>=p_after)
 AND (p_before IS NULL OR j.captured_at<p_before)
 AND (p_session IS NULL OR starts_with(j.session_id,p_session))
), originals AS MATERIALIZED (
 SELECT e.folder_id,s.id AS session_id,s.native_session_id,s.agent,
 (e.event_at AT TIME ZONE p_timezone)::date AS date,count(*) AS event_count
 FROM public.agent_evidence_events e
 JOIN folders f ON f.id=e.folder_id
 JOIN public.agent_evidence_sessions s ON s.id=e.session_id
 JOIN public.agent_evidence_objects o ON o.session_id=e.session_id AND o.object_id=e.object_id
 WHERE e.user_id=p_user_id AND s.user_id=p_user_id AND s.folder_id=e.folder_id
 AND s.deleted_at IS NULL AND e.displayable AND NOT e.inherited
 AND o.committed_revision IS NOT NULL
 AND (p_after IS NULL OR e.event_at>=p_after) AND (p_before IS NULL OR e.event_at<p_before)
 AND (p_session IS NULL OR starts_with(s.native_session_id,p_session) OR s.id::text=p_session)
 GROUP BY e.folder_id,s.id,s.native_session_id,s.agent,(e.event_at AT TIME ZONE p_timezone)::date
)
SELECT jsonb_build_object(
 'snapshot_at',statement_timestamp(),
 'index_pending_objects',(
  SELECT count(*) FROM public.agent_evidence_objects o
  JOIN public.agent_evidence_sessions s ON s.id=o.session_id
  JOIN folders f ON f.id=s.folder_id
  WHERE s.user_id=p_user_id AND s.deleted_at IS NULL AND o.kind='segment'
  AND o.committed_revision IS NOT NULL AND o.indexed_parser_version<1
  AND (p_session IS NULL OR starts_with(s.native_session_id,p_session) OR s.id::text=p_session)
 ),
 'entry_count',(SELECT count(*) FROM journals),
 'original_day_count',(SELECT count(*) FROM originals),
 'entries',coalesce((SELECT jsonb_agg(to_jsonb(j) ORDER BY captured_at,entry_id)
 FROM (SELECT * FROM journals ORDER BY captured_at,entry_id LIMIT 2000) j),'[]'),
 'original_days',coalesce((SELECT jsonb_agg(to_jsonb(o) ORDER BY date,folder_id,session_id)
 FROM (SELECT * FROM originals ORDER BY date,folder_id,session_id LIMIT 2000) o),'[]')
)
$$;
REVOKE ALL ON FUNCTION public.agent_memory_overview(uuid,uuid[],timestamptz,timestamptz,text,text) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.agent_memory_overview(uuid,uuid[],timestamptz,timestamptz,text,text) TO service_role;
COMMIT;
