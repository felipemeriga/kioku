import { createRequire } from "node:module";
import fs from "node:fs";
const require = createRequire(import.meta.url);
const { PGlite } = require(process.env.PGLITE_MODULE || "@electric-sql/pglite");
const db = new PGlite();
await db.exec(
  `CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role; CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY); CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$ SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$; CREATE TABLE folders(id uuid PRIMARY KEY,user_id uuid,kind text); CREATE SCHEMA storage; CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint);`
);
await db.exec(
  "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon,authenticated;"
);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261105090000_agent_evidence.sql",
      import.meta.url
    ),
    "utf8"
  )
);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261105100000_agent_evidence_empty_attachments.sql",
      import.meta.url
    ),
    "utf8"
  )
);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261105103000_agent_evidence_rpc_privileges.sql",
      import.meta.url
    ),
    "utf8"
  )
);

await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261109090000_agent_memory_recall.sql",
      import.meta.url
    ),
    "utf8"
  )
);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261109110000_memory_relevance.sql",
      import.meta.url
    ),
    "utf8"
  )
);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261109120000_memory_latest_order.sql",
      import.meta.url
    ),
    "utf8"
  )
);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261109130000_memory_escape_tokens.sql",
      import.meta.url
    ),
    "utf8"
  )
);
// Keep the prior implementation only in this isolated fixture to prove parity.
const baseline = (await db.query(`SELECT pg_get_functiondef(
  'search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text)'::regprocedure
) body`)).rows[0].body;
await db.exec(baseline.replace("public.search_agent_memory_v2(", "public.memory_search_baseline("));
await db.exec(fs.readFileSync(new URL(
  "../../../supabase/migrations/20261119120000_memory_search_custom_plan.sql",
  import.meta.url
), "utf8"));
// Compare the scalar plan with the previous deployed search as well.
const customPlan = (await db.query(`SELECT pg_get_functiondef(
  'search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text)'::regprocedure
) body`)).rows[0].body;
await db.exec(customPlan.replace("public.search_agent_memory_v2(", "public.memory_search_custom_plan("));
await db.exec(fs.readFileSync(new URL(
  "../../../supabase/migrations/20261127130000_memory_search_scalar_query.sql",
  import.meta.url
), "utf8"));
const identifierPlan = (await db.query(`SELECT pg_get_functiondef(
  'search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text)'::regprocedure
) body`)).rows[0].body;
await db.exec(identifierPlan.replace("public.search_agent_memory_v2(", "public.memory_search_identifier_plan("));
await db.exec(fs.readFileSync(new URL(
  "../../../supabase/migrations/20261127132000_memory_search_index_terms.sql",
  import.meta.url
), "utf8"));
const widthPlan = (await db.query(`SELECT pg_get_functiondef(
  'search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text)'::regprocedure
) body`)).rows[0].body;
await db.exec(widthPlan.replace("public.search_agent_memory_v2(", "public.memory_search_width_plan("));
await db.exec(fs.readFileSync(new URL(
  "../../../supabase/migrations/20261127153031_memory_search_wide_scoring.sql",
  import.meta.url
), "utf8"));
const scorerPlan = (await db.query(`SELECT pg_get_functiondef(
  'search_agent_memory_v2(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text)'::regprocedure
) body`)).rows[0].body;
await db.exec(scorerPlan.replace("public.search_agent_memory_v2(", "public.memory_search_scorer_plan("));
await db.exec(fs.readFileSync(new URL(
  "../../../supabase/migrations/20261127161759_memory_search_bound_density.sql",
  import.meta.url
), "utf8"));
const matchingVectors = (await db.query(`
  WITH docs(v) AS (
    VALUES ($$'alpha':1A,6B 'beta':2D 'alpha_beta':4D$$::tsvector),
           ($$'memória':1A 'operação':6B$$::tsvector),
           (to_tsvector('simple','foo_bar checksum-alpha 31 camelCase arquivo')),
           (to_tsvector('english','threaded query evidence wrapper docs')),
           (''::tsvector)
  ), queries(q) AS (
    SELECT ('('||plainto_tsquery('simple',t)::text||
      CASE WHEN plainto_tsquery('english',t)::text<>''
      THEN ' | '||plainto_tsquery('english',t)::text ELSE '' END||')')::tsquery
    FROM unnest(ARRAY['alpha','alpha_beta','alpha beta','foo_bar','checksum-alpha',
      'camelCase','the','31','docs wrapper','memória','operação','arquivo','nohit']) t
  )
  SELECT bool_and((v@@q)=(strip(v)@@q)) AS identical FROM docs CROSS JOIN queries
`)).rows[0].identical;
if (!matchingVectors) throw Error("stripping positions changed plain boolean term matches");
const identicalVectors = (await db.query(`
  SELECT bool_and(v = (v || ''::tsvector)) AS identical
  FROM unnest(ARRAY[
    ''::tsvector, 'bare'::tsvector, $$'word':3A,7B 'other':1$$::tsvector,
    $$'word':2,3A,5D 'alpha':1C 'omega':10$$::tsvector
  ]) v
`)).rows[0].identical;
if (!identicalVectors) throw Error("detaching a chunk vector changed its positions or weights");
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
const invoke = async (name, args) => (await db.query(
  `SELECT ${name}(${args.map((_, i) => "$" + (i + 1)).join(",")}) value`, args
)).rows[0].value;
const call = async (name, args) => {
  const result = await invoke(name, args);
  if (name === "search_agent_memory_v2") {
    const before = await invoke("memory_search_baseline", args);
    const deployed = await invoke("memory_search_custom_plan", args);
    const identifier = await invoke("memory_search_identifier_plan", args);
    const width = await invoke("memory_search_width_plan", args);
    const scorer = await invoke("memory_search_scorer_plan", args);
    if (JSON.stringify(deployed) !== JSON.stringify(result) ||
        JSON.stringify(identifier) !== JSON.stringify(result) ||
        JSON.stringify(width) !== JSON.stringify(result) ||
        JSON.stringify(scorer) !== JSON.stringify(result))
      throw Error("indexed memory search changed RPC output");
    const normalize = (value) => ({ ...value, matches: value.matches.map(
      (row) => ({ ...row, matched_terms: [...row.matched_terms].sort() })
    ) });
    if (JSON.stringify(normalize(before)) !== JSON.stringify(normalize(result)))
      throw Error("optimized memory search changed results");
  }
  return result;
};
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
  offset = 0
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
  0
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
r = await search2(["gomemlimit", "memory", "upload", "budget"], {
  ids: ["gomemlimit"],
  order: "latest",
});
if (r.total_matches !== 1 || r.matches[0].record_sequence !== 3)
  throw Error("latest identifier focus lost");
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
// Both execution paths retain exact order and metadata across the size boundary.
for (const eventCount of [32767, 32768]) {
  await db.query("UPDATE agent_evidence_sessions SET event_count=$2 WHERE id=$1", [a, eventCount]);
  await search2(["sdk", "archive", "archive", "GOMEMLIMIT", "unknown_symbol"], {
    ids: ["sdk", "gomemlimit", "unknown_symbol"],
    before: "2026-11-07T03:00:00Z",
  });
  await search2(["sdk", "archive"], { session: "01prefix-f", order: "latest" });
  await search2(["", null]);
}
// Qualify the width guard using only projected vector metadata.
await db.query(`
  INSERT INTO agent_memory_chunks
    (session_id,event_id,object_id,user_id,folder_id,char_start,char_length,lexemes)
  SELECT source.session_id,source.event_id,source.object_id,source.user_id,source.folder_id,
         20000+n,1,wide.lexemes
  FROM (SELECT * FROM agent_memory_chunks WHERE session_id=$1 LIMIT 1) source
  CROSS JOIN (SELECT to_tsvector('simple','archive '||string_agg(md5(i::text),' ')) lexemes
              FROM generate_series(1,80) i) wide
  CROSS JOIN generate_series(1,4096) n
`, [a]);
const qualifying = (await db.query(`
  SELECT count(*)::integer AS count FROM agent_memory_chunks WHERE session_id=$1
  AND (pg_column_size(lexemes)>=2048 OR pg_column_compression(lexemes) IS NOT NULL)
`, [a])).rows[0].count;
if (qualifying !== 4096) throw Error("large-search width fixture did not reach the threshold");
await search2(["sdk", "archive", "unknown_symbol"], { ids: ["unknown_symbol"] });
// Higher-base ties span multiple pages. Preserve every lower event in the total.
await db.query(`
  INSERT INTO agent_evidence_events
    (session_id,user_id,folder_id,event_id,object_id,stream_id,generation,record_sequence,
     byte_offset,byte_length,event_at,role,event_type,content_preview,content_length,parser_version)
  SELECT source.session_id,source.user_id,source.folder_id,'prune-'||n,source.object_id,
         source.stream_id,source.generation,20000+n,0,1,'2026-11-05T10:00:00Z',
         'user','message','x',1,source.parser_version
  FROM (SELECT * FROM agent_evidence_events WHERE session_id=$1 LIMIT 1) source
  CROSS JOIN generate_series(1,32) n
`, [a]);
await db.query(`
  INSERT INTO agent_memory_chunks
    (session_id,event_id,object_id,user_id,folder_id,char_start,char_length,lexemes)
  SELECT session_id,event_id,object_id,user_id,folder_id,0,1,to_tsvector('simple',
    CASE WHEN record_sequence<=20012 THEN 'zephyric quasaric astroline nebular'
         WHEN record_sequence=20013 THEN 'zephyric aio'
         ELSE 'zephyric' END)
  FROM agent_evidence_events WHERE session_id=$1 AND event_id LIKE 'prune-%'
`, [a]);
const boundTerms = ["zephyric", "quasaric", "astroline", "nebular", "aio"];
const bounded = await call("search_agent_memory_v2", [
  owner, [first], boundTerms, null, null, null, "relevance", 4, 6, ["aio"], "UTC",
]);
if (bounded.total_matches !== 32 || !bounded.has_more || bounded.matches.length !== 4 ||
    bounded.unmatched_identifiers.length !== 0 ||
    bounded.matches.some(row => row.record_sequence > 20012))
  throw Error("bounded ranking lost order, total, or the pruned weak-identifier witness");
await db.query(`
  INSERT INTO agent_memory_chunks
    (session_id,event_id,object_id,user_id,folder_id,char_start,char_length,lexemes)
  SELECT session_id,event_id,object_id,user_id,folder_id,1,1,to_tsvector('simple','zephyric abi')
  FROM agent_evidence_events WHERE session_id=$1 AND event_id='prune-13'
`, [a]);
await call("search_agent_memory_v2", [
  owner, [first], [...boundTerms, "abi"], null, null, null, "relevance", 4, 6, ["abi"], "UTC",
]);
await db.query("DELETE FROM agent_evidence_events WHERE session_id=$1 AND event_id LIKE 'prune-%'", [a]);
await db.query("DELETE FROM agent_memory_chunks WHERE session_id=$1 AND char_start=24096", [a]);
await search2(["sdk", "archive", "unknown_symbol"], { ids: ["unknown_symbol"] });
await db.query("DELETE FROM agent_memory_chunks WHERE session_id=$1 AND char_start>20000", [a]);
await db.exec(
  "GRANT USAGE ON SCHEMA public,auth TO authenticated; SET ROLE authenticated;"
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
      [signature]
    )
  ).rows[0];
  if (p.a || p.b || !p.s) throw Error("memory RPC privileges");
}
await db.query(
  "UPDATE agent_evidence_objects SET memory_index_version=1 WHERE session_id=$1",
  [a]
);
let upgrade = await call("search_agent_memory_v2", [
  owner,
  [first],
  [],
  null,
  null,
  null,
  "relevance",
  10,
  0,
  [],
  "UTC",
]);
if (upgrade.index_pending_objects !== 1)
  throw Error("legacy vector upgrade was hidden");
const escaped = String.raw`result\nMongoDB acknowledgement\nclock divergence\tGOMEMLIMIT`;
await call("publish_agent_memory_index", [
  a,
  "segment",
  [chunk(2, 9000, escaped)],
  false,
  true,
]);
for (const term of ["mongodb", "clock", "gomemlimit", "nmongodb", "nclock"]) {
  const result = await search(owner, [first], [term]);
  if (
    !result.matches.some(
      (row) => row.char_start === 9000 && row.char_length === escaped.length
    )
  )
    throw Error(
      "escape normalization lost a word or changed the original span: " + term
    );
}
upgrade = await call("search_agent_memory_v2", [
  owner,
  [first],
  [],
  null,
  null,
  null,
  "relevance",
  10,
  0,
  [],
  "UTC",
]);
if (upgrade.index_pending_objects !== 0)
  throw Error("normalized vector was not marked complete");
const version = (
  await db.query(
    "SELECT memory_index_version FROM agent_evidence_objects WHERE session_id=$1",
    [a]
  )
).rows[0].memory_index_version;
if (version !== 2)
  throw Error("legacy publisher contract did not upgrade the vector version");
// Overview inventories original-only days and all dated journal entries in one snapshot.
await db.exec(`CREATE TABLE agent_journal_search_entries(
 user_id uuid,folder_id uuid,session_id text,agent text,title text,body text,
 captured_at timestamptz,entry_id text);`);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261109150000_memory_overview.sql",
      import.meta.url
    ),
    "utf8"
  )
);
await db.exec(
  fs.readFileSync(
    new URL(
      "../../../supabase/migrations/20261109221000_memory_overview_index_coverage.sql",
      import.meta.url
    ),
    "utf8"
  )
);
await db.query(
  `INSERT INTO agent_journal_search_entries VALUES
 ($1,$2,'journal-only','codex','title','early report','2026-11-06T02:00:00Z','early'),
 ($1,$2,'journal-only','codex','title','late correction','2026-11-06T04:00:00Z','late'),
 ($3,$2,'foreign','codex','title','private','2026-11-06T02:00:00Z','foreign')`,
  [owner, first, other]
);
let overview = await call("agent_memory_overview", [
  owner,
  [first],
  null,
  null,
  null,
  "America/Sao_Paulo",
]);
if (
  overview.entry_count !== 2 ||
  overview.entries[1].body !== "late correction"
)
  throw Error("overview lost late entry or leaked foreign owner");
if (
  !overview.original_days.some((d) => d.date === "2026-11-05") ||
  !overview.original_days.some((d) => d.date === "2026-11-06") ||
  overview.original_days.some((d) => d.folder_id !== first)
)
  throw Error("original-only date/scope coverage");
overview = await call("agent_memory_overview", [
  owner,
  [first],
  "2026-11-06T03:00:00Z",
  null,
  "journal-only",
  "UTC",
]);
if (
  overview.entry_count !== 1 ||
  overview.entries[0].entry_id !== "late" ||
  overview.original_day_count !== 0
)
  throw Error("overview session/time boundary");
await db.query(
  "UPDATE agent_evidence_objects SET indexed_parser_version=0 WHERE session_id=$1",
  [a]
);
const pendingOverview = await call("agent_memory_overview", [
  owner,
  [first],
  null,
  null,
  null,
  "UTC",
]);
if (pendingOverview.index_pending_objects !== 1)
  throw Error("unparsed captured originals reported complete");
await db.query(
  "UPDATE agent_evidence_objects SET indexed_parser_version=1 WHERE session_id=$1",
  [a]
);
overview = await call("agent_memory_overview", [
  other,
  [first],
  null,
  null,
  null,
  "UTC",
]);
if (overview.entry_count || overview.original_day_count)
  throw Error("foreign folder authorized");
const permission = (
  await db.query(`SELECT
 has_function_privilege('anon','agent_memory_overview(uuid,uuid[],timestamptz,timestamptz,text,text)','EXECUTE') a,
 has_function_privilege('authenticated','agent_memory_overview(uuid,uuid[],timestamptz,timestamptz,text,text)','EXECUTE') b,
 has_function_privilege('service_role','agent_memory_overview(uuid,uuid[],timestamptz,timestamptz,text,text)','EXECUTE') c`)
).rows[0];
if (permission.a || permission.b || !permission.c)
  throw Error("overview RPC privileges");
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
  "Memory SQL: deep original spans, partial publication, dates, scopes, pagination, RLS and erasure passed"
);
await db.close();
