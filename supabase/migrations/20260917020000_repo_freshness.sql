-- Freshness tracking for generated repo knowledge: the watcher compares the
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
    CONSTRAINT "repo_freshness_pkey" PRIMARY KEY ("folder_id"),
    CONSTRAINT "repo_freshness_folder_id_fkey" FOREIGN KEY ("folder_id")
        REFERENCES "public"."folders"("id") ON DELETE CASCADE,
    CONSTRAINT "repo_freshness_user_id_fkey" FOREIGN KEY ("user_id")
        REFERENCES "auth"."users"("id") ON DELETE CASCADE
);

ALTER TABLE "public"."repo_freshness" OWNER TO "postgres";
