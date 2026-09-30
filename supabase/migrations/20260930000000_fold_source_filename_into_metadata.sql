-- Doc retrieval showed "unknown" as the source for some chunks (e.g. Notion
-- pages). The name lives in the top-level `source_filename` column, but the
-- search RPCs only returned the `metadata` jsonb — and Notion docs don't carry
-- source_filename inside metadata. The chat citations and the debug inspector
-- both read metadata->>'source_filename', so they fell back to "unknown".
--
-- Fold the column into the returned metadata (preferring source_filename, then
-- the Notion parent path, trimmed). Same RETURNS signature, so CREATE OR
-- REPLACE works and no backend code changes are needed.
CREATE OR REPLACE FUNCTION public.match_documents(
  query_embedding vector, match_count integer DEFAULT 5,
  filter_user_id uuid DEFAULT NULL::uuid, filter_topic text DEFAULT NULL::text,
  filter_keyword text DEFAULT NULL::text, filter_root_folder_id uuid DEFAULT NULL::uuid,
  filter_folder_ids uuid[] DEFAULT NULL::uuid[], filter_source_filename text DEFAULT NULL::text,
  filter_created_after timestamp with time zone DEFAULT NULL::timestamp with time zone,
  filter_created_before timestamp with time zone DEFAULT NULL::timestamp with time zone)
RETURNS TABLE(id uuid, content text, metadata jsonb, similarity double precision, created_at timestamp with time zone, source_type text)
LANGUAGE sql STABLE AS $function$
    SELECT id, content,
      COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
        'source_filename',
        NULLIF(trim(COALESCE(source_filename, notion_parent_path)), '')) AS metadata,
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
$function$;

CREATE OR REPLACE FUNCTION public.keyword_search(
  search_query text, match_count integer DEFAULT 20,
  filter_user_id uuid DEFAULT NULL::uuid, filter_topic text DEFAULT NULL::text,
  filter_keyword text DEFAULT NULL::text, filter_root_folder_id uuid DEFAULT NULL::uuid,
  filter_folder_ids uuid[] DEFAULT NULL::uuid[], filter_source_filename text DEFAULT NULL::text,
  filter_created_after timestamp with time zone DEFAULT NULL::timestamp with time zone,
  filter_created_before timestamp with time zone DEFAULT NULL::timestamp with time zone)
RETURNS TABLE(id uuid, content text, metadata jsonb, rank real, created_at timestamp with time zone, source_type text)
LANGUAGE sql STABLE AS $function$
    SELECT id, content,
      COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
        'source_filename',
        NULLIF(trim(COALESCE(source_filename, notion_parent_path)), '')) AS metadata,
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
$function$;
