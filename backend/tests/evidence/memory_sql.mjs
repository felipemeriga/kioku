import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(import.meta.url);
const { PGlite } = require(process.env.PGLITE_MODULE || "@electric-sql/pglite");
const db = new PGlite();
await db.exec(
  `CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role; CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY); CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$ SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$; CREATE TABLE folders(id uuid PRIMARY KEY,user_id uuid,kind text); CREATE SCHEMA storage; CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint);`,
);
await db.exec(
  "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon,authenticated;",
);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261105090000_agent_evidence.sql",
      import.meta.url,
    ),
    "utf8",
  ),
);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261105100000_agent_evidence_empty_attachments.sql",
      import.meta.url,
    ),
    "utf8",
  ),
);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261105103000_agent_evidence_rpc_privileges.sql",
      import.meta.url,
    ),
    "utf8",
  ),
);

await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261109090000_agent_memory_recall.sql",
      import.meta.url,
    ),
    "utf8",
  ),
);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261109110000_memory_relevance.sql",
      import.meta.url,
    ),
    "utf8",
  ),
);
const owner = "11111111-1111-4111-8111-111111111111",
  other = "11111111-1111-4111-8111-111111111112";
const first = "22222222-2222-4222-8222-222222222222",
  second = "22222222-2222-4222-8222-222222222223";
await db.query("INSERT INTO auth.users VALUES($1),($2)", [owner, other]);
await db.query("INSERT INTO folders VALUES($1,$3,'repo'),($2,$3,'repo')", [
  first,
  second,
  owner,
]);
const call = async (name, args) =>
  (
    await db.query(
      `SELECT ${name}(${args.map((_, i) => "$" + (i + 1)).join(",")}) value`,
      args,
    )
  ).rows[0].value;
const descriptor = {
  id: "segment",
  kind: "segment",
  sha256: "a".repeat(64),
  byte_length: 300,
  stream_id: "native",
  generation: 1,
  source_start: 0,
  source_end: 300,
  first_record: 1,
  last_record: 3,
  record_count: 3,
};
async function seed(folder, native) {
  const body = {
    folder_id: folder,
    agent: "codex",
    native_session_id: native,
    producer_id: "pc",
    batch_id: native,
    base_revision: 0,
    objects: [descriptor],
    gaps: [],
    lifecycle: { status: "observed" },
  };
  const p = await call("prepare_agent_evidence", [owner, body]);
  const lease = await call("claim_agent_evidence_upload", [
    owner,
    p.session_id,
    "segment",
  ]);
  await call("finish_agent_evidence_upload", [
    owner,
    p.session_id,
    "segment",
    lease.nonce,
    "test/segment",
  ]);
  await call("commit_agent_evidence", [owner, native]);
  const events = [1, 2, 3].map((n) => ({
    event_id: String(n).repeat(64),
    stream_id: "native",
    generation: 1,
    record_sequence: n,
    byte_offset: (n - 1) * 100,
    byte_length: 100,
    event_at: n < 3 ? "2026-11-06T02:00:00Z" : "2026-11-06T04:00:00Z",
    role: "assistant",
    event_type: "message",
    content_preview: "short preview",
    displayable: true,
  }));
  await call("publish_agent_evidence_index", [
    p.session_id,
    "segment",
    events,
    {},
    1,
    true,
  ]);
  return p.session_id;
}
const a = await seed(first, "01prefix-first"),
  b = await seed(second, "01prefix-second");
const chunk = (event, start, text) => ({
  event_id: String(event).repeat(64),
  char_start: start,
  char_length: text.length,
  text,
});
await call("publish_agent_memory_index", [
  a,
  "segment",
  [
    chunk(1, 0, "Earlier GOMEMLIMIT=3GiB experiment"),
    chunk(2, 6000, "Deep original needle GOMEMLIMIT=4GiB"),
    chunk(3, 0, "Future GOMEMLIMIT=5GiB request"),
  ],
  true,
  false,
]);
const search = (
  user = owner,
  folders = [first],
  terms = ["gomemlimit"],
  after = null,
  before = null,
  session = null,
  order = "chronological",
  limit = 20,
  offset = 0,
) =>
  call("search_agent_memory", [
    user,
    folders,
    terms,
    after,
    before,
    session,
    order,
    limit,
    offset,
  ]);
let r = await search();
if (r.total_matches !== 0 || r.index_pending_objects !== 1)
  throw Error("partial index became searchable");
await call("publish_agent_memory_index", [a, "segment", [], false, true]);
await call("publish_agent_memory_index", [
  b,
  "segment",
  [chunk(1, 0, "Other repo GOMEMLIMIT=4GiB")],
  true,
  true,
]);
r = await search();
if (r.total_matches !== 3) throw Error("lexical matches missing");
r = await search(owner, [first], ["needle"]);
if (r.matches[0].char_start !== 6000) throw Error("deep evidence was lost");
r = await search(owner, [first], ["gomemlimit"], null, "2026-11-06T03:00:00Z");
if (r.total_matches !== 2) throw Error("as-of leaked later knowledge");
r = await search(owner, [first], [], "2026-11-07T00:00:00Z");
if (r.total_matches !== 0) throw Error("empty date scope broadened");
r = await search(owner, [first, second]);
if (r.total_matches !== 4) throw Error("cross-repo root missing");
r = await search(owner, [first], [], null, null, "01prefix-f");
if (r.total_matches !== 3) throw Error("session prefix missing");
r = await search(other, [first, second]);
if (r.total_matches !== 0) throw Error("cross-tenant leak");
r = await search(
  owner,
  [first],
  ["gomemlimit"],
  null,
  null,
  null,
  "latest",
  1,
  0,
);
if (r.matches[0].record_sequence !== 3 || !r.has_more)
  throw Error("latest pagination");
await call("publish_agent_memory_index", [
  a,
  "segment",
  [
    chunk(1, 0, "SDK ".repeat(80) + "hook memory upload budget"),
    chunk(2, 0, "The newer SDK archive failed to link: missing core symbols"),
    chunk(3, 0, "GOMEMLIMIT=4GiB chosen"),
  ],
  true,
  true,
]);
const search2 = (terms, opts = {}) =>
  call("search_agent_memory_v2", [
    owner,
    [first],
    terms,
    null,
    opts.before || null,
    opts.session || null,
    opts.order || "relevance",
    10,
    0,
    opts.ids || [],
    "America/Sao_Paulo",
  ]);
r = await search2(["sdk", "newer", "archive", "link", "missing"], {
  ids: ["sdk"],
});
if (r.matches[0].record_sequence !== 2)
  throw Error("SDK frequency buried the specific link failure");
if (!r.matches[0].matched_terms.includes("archive"))
  throw Error("lost matched terms");
r = await search2(["gomemlimit", "memory", "upload", "budget"], {
  ids: ["gomemlimit"],
});
if (r.matches[0].record_sequence !== 3)
  throw Error("explicit identifier buried by generic terms");
r = await search2(["sdk"], {
  before: "2026-11-06T03:00:00Z",
  session: "01prefix-f",
});
if (
  r.total_matches !== 2 ||
  r.matches.some((x) => x.event_at >= "2026-11-06T03:00:00+00:00")
)
  throw Error("v2 time/session scope leaked");
r = await call("search_agent_memory_v2", [other, [first], ["sdk"]]);
if (r.total_matches !== 0) throw Error("v2 cross-tenant leak");
r = await search2(["unknown_symbol", "archive"], { ids: ["unknown_symbol"] });
if (!r.unmatched_identifiers.includes("unknown_symbol"))
  throw Error("identifier miss was hidden");
await db.exec(
  "GRANT USAGE ON SCHEMA public,auth TO authenticated; SET ROLE authenticated;",
);
await db.query("SELECT set_config('request.jwt.claim.sub',$1,false)", [other]);
if ((await db.query("SELECT * FROM agent_memory_chunks")).rows.length)
  throw Error("memory RLS leak");
await db.exec("RESET ROLE");
for (const signature of [
  "search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text)",
  "publish_agent_memory_index(uuid,text,jsonb,boolean,boolean)",
  "search_agent_memory(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer)",
]) {
  const p = (
    await db.query(
      "SELECT has_function_privilege('anon',$1,'EXECUTE') a,has_function_privilege('authenticated',$1,'EXECUTE') b,has_function_privilege('service_role',$1,'EXECUTE') s",
      [signature],
    )
  ).rows[0];
  if (p.a || p.b || !p.s) throw Error("memory RPC privileges");
}
await call("delete_agent_evidence", [owner, first, a]);
if ((await search()).total_matches !== 0)
  throw Error("tombstone still searchable");
await db.query("DELETE FROM agent_evidence_sessions WHERE id=$1", [a]);
if (
  (await db.query("SELECT * FROM agent_memory_chunks WHERE session_id=$1", [a]))
    .rows.length
)
  throw Error("memory projection survived erase");
console.log(
  "Memory SQL: deep original spans, partial publication, dates, scopes, pagination, RLS and erasure passed",
);
await db.close();
