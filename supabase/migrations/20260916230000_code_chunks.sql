-- Semantic code search: symbol-aware chunks of repo source code, embedded
-- with a code-tuned model (voyage-code-3) in a SEPARATE vector space from
-- documents (different embedding model => never mixed in one index).

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
