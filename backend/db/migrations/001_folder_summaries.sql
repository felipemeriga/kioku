-- Folder Summaries
--
-- Stores the nightly-generated "orientation" for each folder: a compact,
-- structured JSON summary of what the folder contains. Optimized for:
--   * incremental updates via delta prompts (previous_content + change lists)
--   * cheap skip-if-unchanged detection (included_hashes)
--   * time-series history so the UI can diff two consecutive summaries

create table if not exists "public"."folder_summaries" (
    "id" uuid default gen_random_uuid() not null,
    "folder_id" uuid not null,
    "user_id" uuid not null,
    "generated_at" timestamp with time zone default now() not null,
    "kind" text not null,
    "content" jsonb not null,
    "previous_content" jsonb,
    "included_hashes" jsonb default '[]'::jsonb not null,
    "doc_count" integer default 0 not null,
    "changed_files" jsonb default '{}'::jsonb not null,
    "input_tokens" integer,
    "output_tokens" integer,
    "duration_ms" integer,
    "trigger" text,
    constraint "folder_summaries_pkey" primary key ("id"),
    constraint "folder_summaries_kind_check" check ("kind" = any (array['full'::text, 'delta'::text, 'seed'::text])),
    constraint "folder_summaries_trigger_check" check ("trigger" is null or "trigger" = any (array['cron_nightly'::text, 'cron_weekly'::text, 'manual'::text, 'seed'::text])),
    constraint "folder_summaries_folder_id_fkey" foreign key ("folder_id") references "public"."folders"("id") on delete cascade,
    constraint "folder_summaries_user_id_fkey" foreign key ("user_id") references "auth"."users"("id") on delete cascade
);

create index if not exists "folder_summaries_folder_id_generated_at_idx"
  on "public"."folder_summaries" using btree ("folder_id", "generated_at" desc);

create index if not exists "folder_summaries_user_id_idx"
  on "public"."folder_summaries" using btree ("user_id");

alter table "public"."folder_summaries" enable row level security;

drop policy if exists "Users manage own folder summaries" on "public"."folder_summaries";
create policy "Users manage own folder summaries" on "public"."folder_summaries"
  using ("auth"."uid"() = "user_id")
  with check ("auth"."uid"() = "user_id");
