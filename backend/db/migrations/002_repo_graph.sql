-- Repo Code Graph
--
-- A per-repo symbol + reference graph so coding agents can query structure
-- (definitions, references, outlines, blast-radius) via MCP instead of
-- grepping. Populated client-side by `kioku index` (tree-sitter AST extraction
-- via Graphify), uploaded as per-file deltas, and merged here.
--
-- Model (mirrors the extractor's ownership rules):
--   * A node ("symbol") is OWNED by its `file`. Re-indexing a file replaces
--     all of that file's nodes.
--   * An edge is OWNED by `ref_file` (the file the reference appears in).
--     Re-indexing a file replaces all edges originating in it.
--   * Node IDs are deterministic (repo-relative path + symbol), so unchanged
--     symbols keep identity across re-indexes and cross-file edges resolve by
--     ID. Dangling edges (endpoint missing) are dropped at QUERY time
--     (fail-closed) — no reverse-dependency recompute needed.

create table if not exists "public"."repo_symbols" (
    "folder_id" uuid not null,
    "user_id" uuid not null,
    "node_id" text not null,
    "symbol" text not null,
    "kind" text,
    "file" text not null,
    "start_line" integer,
    "origin" text,
    "updated_at" timestamp with time zone default now() not null,
    constraint "repo_symbols_pkey" primary key ("folder_id", "node_id"),
    constraint "repo_symbols_folder_id_fkey" foreign key ("folder_id") references "public"."folders"("id") on delete cascade,
    constraint "repo_symbols_user_id_fkey" foreign key ("user_id") references "auth"."users"("id") on delete cascade
);

create index if not exists "repo_symbols_symbol_idx"
  on "public"."repo_symbols" using btree ("folder_id", "symbol");
create index if not exists "repo_symbols_file_idx"
  on "public"."repo_symbols" using btree ("folder_id", "file");

create table if not exists "public"."repo_edges" (
    "id" uuid default gen_random_uuid() not null,
    "folder_id" uuid not null,
    "user_id" uuid not null,
    "src_node_id" text not null,
    "dst_node_id" text not null,
    "relation" text not null,
    "confidence" text,
    "ref_file" text,
    "ref_line" integer,
    constraint "repo_edges_pkey" primary key ("id"),
    constraint "repo_edges_folder_id_fkey" foreign key ("folder_id") references "public"."folders"("id") on delete cascade,
    constraint "repo_edges_user_id_fkey" foreign key ("user_id") references "auth"."users"("id") on delete cascade
);

create index if not exists "repo_edges_src_idx"
  on "public"."repo_edges" using btree ("folder_id", "src_node_id");
create index if not exists "repo_edges_dst_idx"
  on "public"."repo_edges" using btree ("folder_id", "dst_node_id");
create index if not exists "repo_edges_ref_file_idx"
  on "public"."repo_edges" using btree ("folder_id", "ref_file");

create table if not exists "public"."repo_graph_meta" (
    "folder_id" uuid not null,
    "user_id" uuid not null,
    "last_indexed_sha" text,
    "node_count" integer default 0 not null,
    "edge_count" integer default 0 not null,
    "updated_at" timestamp with time zone default now() not null,
    constraint "repo_graph_meta_pkey" primary key ("folder_id"),
    constraint "repo_graph_meta_folder_id_fkey" foreign key ("folder_id") references "public"."folders"("id") on delete cascade,
    constraint "repo_graph_meta_user_id_fkey" foreign key ("user_id") references "auth"."users"("id") on delete cascade
);

alter table "public"."repo_symbols" enable row level security;
alter table "public"."repo_edges" enable row level security;
alter table "public"."repo_graph_meta" enable row level security;

drop policy if exists "Users manage own repo symbols" on "public"."repo_symbols";
create policy "Users manage own repo symbols" on "public"."repo_symbols"
  using ("auth"."uid"() = "user_id")
  with check ("auth"."uid"() = "user_id");

drop policy if exists "Users manage own repo edges" on "public"."repo_edges";
create policy "Users manage own repo edges" on "public"."repo_edges"
  using ("auth"."uid"() = "user_id")
  with check ("auth"."uid"() = "user_id");

drop policy if exists "Users manage own repo graph meta" on "public"."repo_graph_meta";
create policy "Users manage own repo graph meta" on "public"."repo_graph_meta"
  using ("auth"."uid"() = "user_id")
  with check ("auth"."uid"() = "user_id");
