-- Folder-switch latency: the /api/folders/{id}/breadcrumbs route walked the
-- parent chain one Supabase round-trip at a time (O(depth) sequential calls,
-- ~150ms each). Collapse the whole chain into a single recursive-CTE call so
-- breadcrumbs cost one round-trip regardless of how deep the folder is nested.

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
  ORDER BY depth DESC;  -- root first, leaf last
$$;

ALTER FUNCTION "public"."folder_breadcrumbs"("p_folder_id" "uuid", "p_user_id" "uuid") OWNER TO "postgres";
