-- Temporal retrieval: search results carry created_at + source_type (so the
-- agent can see and reason about document age) and accept
-- filter_created_after / filter_created_before for date-bounded queries.
-- Return-type changes require DROP + CREATE.

DROP FUNCTION IF EXISTS "public"."match_documents"(
    "public"."vector", integer, "uuid", "text", "text", "uuid", "uuid"[], "text");
DROP FUNCTION IF EXISTS "public"."keyword_search"(
    "text", integer, "uuid", "text", "text", "uuid", "uuid"[], "text");

CREATE FUNCTION "public"."match_documents"(
    "query_embedding" "public"."vector",
    "match_count" integer DEFAULT 5,
    "filter_user_id" "uuid" DEFAULT NULL::"uuid",
    "filter_topic" "text" DEFAULT NULL::"text",
    "filter_keyword" "text" DEFAULT NULL::"text",
    "filter_root_folder_id" "uuid" DEFAULT NULL::"uuid",
    "filter_folder_ids" "uuid"[] DEFAULT NULL::"uuid"[],
    "filter_source_filename" "text" DEFAULT NULL::"text",
    "filter_created_after" timestamp with time zone DEFAULT NULL,
    "filter_created_before" timestamp with time zone DEFAULT NULL
) RETURNS TABLE(
    "id" "uuid",
    "content" "text",
    "metadata" "jsonb",
    "similarity" double precision,
    "created_at" timestamp with time zone,
    "source_type" "text"
)
    LANGUAGE "sql" STABLE
    AS $$
    SELECT id, content, metadata,
      1 - (embedding <=> query_embedding) AS similarity,
      created_at, source_type
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

ALTER FUNCTION "public"."match_documents"(
    "public"."vector", integer, "uuid", "text", "text", "uuid", "uuid"[], "text",
    timestamp with time zone, timestamp with time zone)
    OWNER TO "postgres";

CREATE FUNCTION "public"."keyword_search"(
    "search_query" "text",
    "match_count" integer DEFAULT 20,
    "filter_user_id" "uuid" DEFAULT NULL::"uuid",
    "filter_topic" "text" DEFAULT NULL::"text",
    "filter_keyword" "text" DEFAULT NULL::"text",
    "filter_root_folder_id" "uuid" DEFAULT NULL::"uuid",
    "filter_folder_ids" "uuid"[] DEFAULT NULL::"uuid"[],
    "filter_source_filename" "text" DEFAULT NULL::"text",
    "filter_created_after" timestamp with time zone DEFAULT NULL,
    "filter_created_before" timestamp with time zone DEFAULT NULL
) RETURNS TABLE(
    "id" "uuid",
    "content" "text",
    "metadata" "jsonb",
    "rank" real,
    "created_at" timestamp with time zone,
    "source_type" "text"
)
    LANGUAGE "sql" STABLE
    AS $$
    SELECT id, content, metadata,
      ts_rank(fts, websearch_to_tsquery('english', search_query)) AS rank,
      created_at, source_type
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

ALTER FUNCTION "public"."keyword_search"(
    "text", integer, "uuid", "text", "text", "uuid", "uuid"[], "text",
    timestamp with time zone, timestamp with time zone)
    OWNER TO "postgres";
