-- Detailed repo documentation — a large, agent-authored markdown doc per repo
-- folder. Stored here (not in the injected briefing); fetched on-demand via the
-- get_repo_documentation MCP tool. The abstract also lands in the briefing's
-- `documentation` section so it injects each session. Latest row per folder is
-- the current doc; `generated_at` drives the 30-day staleness clock.

create table if not exists "public"."repo_documentation" (
    "id" uuid default gen_random_uuid() not null,
    "folder_id" uuid not null,
    "user_id" uuid not null,
    "content" text not null,
    "abstract" text,
    "generated_at" timestamp with time zone default now() not null,
    "created_at" timestamp with time zone default now() not null,
    constraint "repo_documentation_pkey" primary key ("id"),
    constraint "repo_documentation_folder_id_fkey" foreign key ("folder_id")
        references "public"."folders"("id") on delete cascade,
    constraint "repo_documentation_user_id_fkey" foreign key ("user_id")
        references "auth"."users"("id") on delete cascade
);

create index if not exists "repo_documentation_folder_generated_idx"
    on "public"."repo_documentation" using btree ("folder_id", "generated_at" desc);

alter table "public"."repo_documentation" enable row level security;

drop policy if exists "Users manage own repo documentation" on "public"."repo_documentation";
create policy "Users manage own repo documentation" on "public"."repo_documentation"
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
