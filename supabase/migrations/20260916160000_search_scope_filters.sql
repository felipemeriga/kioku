-- RAG scoping: allow retrieval restricted to a folder subtree (any folder,
-- not just a root) or to a single document. The old 6-arg overloads must be
-- dropped first — adding defaulted params as CREATE OR REPLACE would create a
-- second overload and make PostgREST rpc dispatch ambiguous.

DROP FUNCTION IF EXISTS "public"."match_documents"(
    "public"."vector", integer, "uuid", "text", "text", "uuid");
DROP FUNCTION IF EXISTS "public"."keyword_search"(
    "text", integer, "uuid", "text", "text", "uuid");

CREATE FUNCTION "public"."match_documents"(
    "query_embedding" "public"."vector",
    "match_count" integer DEFAULT 5,
    "filter_user_id" "uuid" DEFAULT NULL::"uuid",
    "filter_topic" "text" DEFAULT NULL::"text",
    "filter_keyword" "text" DEFAULT NULL::"text",
    "filter_root_folder_id" "uuid" DEFAULT NULL::"uuid",
    "filter_folder_ids" "uuid"[] DEFAULT NULL::"uuid"[],
    "filter_source_filename" "text" DEFAULT NULL::"text"
) RETURNS TABLE("id" "uuid", "content" "text", "metadata" "jsonb", "similarity" double precision)
    LANGUAGE "sql" STABLE
    AS $$
    SELECT id, content, metadata,
      1 - (embedding <=> query_embedding) AS similarity
    FROM documents
    WHERE (user_id = filter_user_id OR user_id IS NULL)
      AND (filter_topic IS NULL OR metadata->>'topic' = filter_topic)
      AND (filter_keyword IS NULL OR metadata->'keywords' ? filter_keyword)
      AND (filter_root_folder_id IS NULL OR root_folder_id = filter_root_folder_id)
      AND (filter_folder_ids IS NULL OR folder_id = ANY(filter_folder_ids))
      AND (filter_source_filename IS NULL OR source_filename = filter_source_filename)
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
  $$;

ALTER FUNCTION "public"."match_documents"(
    "public"."vector", integer, "uuid", "text", "text", "uuid", "uuid"[], "text")
    OWNER TO "postgres";

CREATE FUNCTION "public"."keyword_search"(
    "search_query" "text",
    "match_count" integer DEFAULT 20,
    "filter_user_id" "uuid" DEFAULT NULL::"uuid",
    "filter_topic" "text" DEFAULT NULL::"text",
    "filter_keyword" "text" DEFAULT NULL::"text",
    "filter_root_folder_id" "uuid" DEFAULT NULL::"uuid",
    "filter_folder_ids" "uuid"[] DEFAULT NULL::"uuid"[],
    "filter_source_filename" "text" DEFAULT NULL::"text"
) RETURNS TABLE("id" "uuid", "content" "text", "metadata" "jsonb", "rank" real)
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
      AND (filter_folder_ids IS NULL OR folder_id = ANY(filter_folder_ids))
      AND (filter_source_filename IS NULL OR source_filename = filter_source_filename)
    ORDER BY rank DESC
    LIMIT match_count;
  $$;

ALTER FUNCTION "public"."keyword_search"(
    "text", integer, "uuid", "text", "text", "uuid", "uuid"[], "text")
    OWNER TO "postgres";
