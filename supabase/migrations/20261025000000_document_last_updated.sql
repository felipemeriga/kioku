-- Content freshness is separate from chunk ingestion. Do not mark the entire
-- existing corpus fresh on migration; source edit timestamps can represent
-- no-op Notion touches, so the conservative backfill is created_at.
BEGIN;

ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS last_updated timestamptz;
UPDATE public.documents SET last_updated = coalesce(created_at, now()) WHERE last_updated IS NULL;
ALTER TABLE public.documents ALTER COLUMN last_updated SET DEFAULT now();
ALTER TABLE public.documents ALTER COLUMN last_updated SET NOT NULL;

CREATE OR REPLACE FUNCTION public.track_document_content_update()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  NEW.created_at := OLD.created_at;
  IF NEW.content IS DISTINCT FROM OLD.content OR NEW.content_hash IS DISTINCT FROM OLD.content_hash THEN
    NEW.last_updated := statement_timestamp();
  ELSE
    -- Sync metadata, embedding regeneration and identical writes are not new
    -- knowledge. Even an explicitly supplied timestamp must not freshen them.
    NEW.last_updated := OLD.last_updated;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS documents_content_updated ON public.documents;
CREATE TRIGGER documents_content_updated BEFORE UPDATE ON public.documents
FOR EACH ROW EXECUTE FUNCTION public.track_document_content_update();

-- Adding a return column requires recreating these exact overloads. Preserve
-- the existing user/folder/date filters and security-invoker behavior.
DROP FUNCTION public.match_documents(vector, integer, uuid, text, text, uuid, uuid[], text, timestamptz, timestamptz);
CREATE FUNCTION public.match_documents(
  query_embedding vector, match_count integer DEFAULT 5,
  filter_user_id uuid DEFAULT NULL, filter_topic text DEFAULT NULL,
  filter_keyword text DEFAULT NULL, filter_root_folder_id uuid DEFAULT NULL,
  filter_folder_ids uuid[] DEFAULT NULL, filter_source_filename text DEFAULT NULL,
  filter_created_after timestamptz DEFAULT NULL, filter_created_before timestamptz DEFAULT NULL
) RETURNS TABLE(id uuid, content text, metadata jsonb, similarity double precision,
  created_at timestamptz, source_type text, last_updated timestamptz)
LANGUAGE sql STABLE AS $$
  SELECT id, content, metadata, 1 - (embedding <=> query_embedding) AS similarity,
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
  ORDER BY embedding <=> query_embedding LIMIT match_count;
$$;

DROP FUNCTION public.keyword_search(text, integer, uuid, text, text, uuid, uuid[], text, timestamptz, timestamptz);
CREATE FUNCTION public.keyword_search(
  search_query text, match_count integer DEFAULT 20,
  filter_user_id uuid DEFAULT NULL, filter_topic text DEFAULT NULL,
  filter_keyword text DEFAULT NULL, filter_root_folder_id uuid DEFAULT NULL,
  filter_folder_ids uuid[] DEFAULT NULL, filter_source_filename text DEFAULT NULL,
  filter_created_after timestamptz DEFAULT NULL, filter_created_before timestamptz DEFAULT NULL
) RETURNS TABLE(id uuid, content text, metadata jsonb, rank real,
  created_at timestamptz, source_type text, last_updated timestamptz)
LANGUAGE sql STABLE AS $$
  SELECT id, content, metadata, ts_rank(fts, websearch_to_tsquery('english', search_query)) AS rank,
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
  ORDER BY rank DESC LIMIT match_count;
$$;

GRANT EXECUTE ON FUNCTION public.match_documents(vector, integer, uuid, text, text, uuid, uuid[], text, timestamptz, timestamptz) TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.keyword_search(text, integer, uuid, text, text, uuid, uuid[], text, timestamptz, timestamptz) TO anon, authenticated, service_role;
NOTIFY pgrst, 'reload schema';
COMMIT;
