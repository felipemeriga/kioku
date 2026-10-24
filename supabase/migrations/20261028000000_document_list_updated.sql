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

NOTIFY pgrst, 'reload schema';
