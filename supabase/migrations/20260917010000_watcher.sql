-- Multi-user repo watcher: per-user git deploy identity + registry of
-- watched repos. Private keys and minted watcher api keys are stored
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
