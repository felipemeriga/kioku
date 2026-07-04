-- Phase 1 + 2: Mem0 + GitHub integrations + retrieval audit log
--
-- Mem0 and GitHub are treated as integrations (like notion_sync_configs):
-- users bind a folder to a Mem0 API key or a GitHub repo, and the app
-- proxies queries / ingests activity from that source.
--
-- retrieval_log is the audit surface — one row per retrieval call, so we can
-- measure "which memory got retrieved for which query, when, and did it
-- actually get used." This is what makes the memory system evaluable.

-- ─── mem0_sync_configs ───────────────────────────────────────────────
create table if not exists "public"."mem0_sync_configs" (
    "id" uuid default gen_random_uuid() not null,
    "user_id" uuid not null,
    "root_folder_id" uuid not null,
    "api_key_encrypted" text not null,
    "org_id" text,
    "project_id" text,
    "last_verified_at" timestamptz,
    "last_error" text,
    "created_at" timestamptz default now(),
    "updated_at" timestamptz default now(),
    constraint "mem0_sync_configs_pkey" primary key ("id"),
    constraint "mem0_sync_configs_folder_unique" unique ("user_id", "root_folder_id"),
    constraint "mem0_sync_configs_user_fk"
      foreign key ("user_id") references "auth"."users"("id") on delete cascade,
    constraint "mem0_sync_configs_folder_fk"
      foreign key ("root_folder_id") references "public"."folders"("id") on delete cascade
);
create index if not exists "idx_mem0_sync_configs_user_id"
  on "public"."mem0_sync_configs" using btree ("user_id");

alter table "public"."mem0_sync_configs" enable row level security;
drop policy if exists "Users manage own mem0 configs" on "public"."mem0_sync_configs";
create policy "Users manage own mem0 configs" on "public"."mem0_sync_configs"
  using ("auth"."uid"() = "user_id")
  with check ("auth"."uid"() = "user_id");

create or replace trigger "mem0_sync_configs_updated_at"
  before update on "public"."mem0_sync_configs"
  for each row execute function "public"."update_updated_at"();


-- ─── github_sync_configs ─────────────────────────────────────────────
create table if not exists "public"."github_sync_configs" (
    "id" uuid default gen_random_uuid() not null,
    "user_id" uuid not null,
    "root_folder_id" uuid not null,
    "repo_owner" text not null,
    "repo_name" text not null,
    "token_encrypted" text,
    "since_days" integer default 14 not null,
    "last_synced_at" timestamptz,
    "last_error" text,
    "created_at" timestamptz default now(),
    "updated_at" timestamptz default now(),
    constraint "github_sync_configs_pkey" primary key ("id"),
    constraint "github_sync_configs_folder_unique" unique ("user_id", "root_folder_id"),
    constraint "github_sync_configs_user_fk"
      foreign key ("user_id") references "auth"."users"("id") on delete cascade,
    constraint "github_sync_configs_folder_fk"
      foreign key ("root_folder_id") references "public"."folders"("id") on delete cascade,
    constraint "github_sync_configs_since_days_check" check ("since_days" between 1 and 365)
);
create index if not exists "idx_github_sync_configs_user_id"
  on "public"."github_sync_configs" using btree ("user_id");

alter table "public"."github_sync_configs" enable row level security;
drop policy if exists "Users manage own github configs" on "public"."github_sync_configs";
create policy "Users manage own github configs" on "public"."github_sync_configs"
  using ("auth"."uid"() = "user_id")
  with check ("auth"."uid"() = "user_id");

create or replace trigger "github_sync_configs_updated_at"
  before update on "public"."github_sync_configs"
  for each row execute function "public"."update_updated_at"();


-- ─── retrieval_log ───────────────────────────────────────────────────
create table if not exists "public"."retrieval_log" (
    "id" uuid default gen_random_uuid() not null,
    "user_id" uuid not null,
    "folder_id" uuid,
    "query" text not null,
    "sources_hit" jsonb default '[]'::jsonb not null,
    "chunks_returned" integer default 0 not null,
    "chunk_ids" jsonb default '[]'::jsonb not null,
    "latency_ms" integer,
    "channel" text,
    "conversation_id" uuid,
    "created_at" timestamptz default now(),
    constraint "retrieval_log_pkey" primary key ("id"),
    constraint "retrieval_log_user_fk"
      foreign key ("user_id") references "auth"."users"("id") on delete cascade,
    constraint "retrieval_log_folder_fk"
      foreign key ("folder_id") references "public"."folders"("id") on delete set null
);
create index if not exists "idx_retrieval_log_user_id_created_at"
  on "public"."retrieval_log" using btree ("user_id", "created_at" desc);
create index if not exists "idx_retrieval_log_folder_id"
  on "public"."retrieval_log" using btree ("folder_id")
  where "folder_id" is not null;

alter table "public"."retrieval_log" enable row level security;
drop policy if exists "Users read own retrieval log" on "public"."retrieval_log";
create policy "Users read own retrieval log" on "public"."retrieval_log"
  for select using ("auth"."uid"() = "user_id");
drop policy if exists "Users insert own retrieval log" on "public"."retrieval_log";
create policy "Users insert own retrieval log" on "public"."retrieval_log"
  for insert with check ("auth"."uid"() = "user_id");
