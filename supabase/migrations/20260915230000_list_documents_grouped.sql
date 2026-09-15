-- Folder listing performance: the /api/documents route used to pull one row
-- per CHUNK and group in Python — O(chunks) payload for an O(files) view.
-- Aggregate in SQL instead, and give the filter a covering index.

CREATE INDEX IF NOT EXISTS "idx_documents_user_folder_created"
    ON "public"."documents" USING "btree" ("user_id", "folder_id", "created_at" DESC);

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
