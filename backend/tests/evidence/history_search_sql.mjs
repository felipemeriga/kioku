import fs from 'node:fs';
import assert from 'node:assert/strict';
import {PGlite} from '@electric-sql/pglite';
import {pg_trgm} from '@electric-sql/pglite/contrib/pg_trgm';
const db=new PGlite({extensions:{pg_trgm}});
await db.exec(`CREATE ROLE anon;CREATE ROLE authenticated;CREATE ROLE service_role;CREATE SCHEMA extensions;
CREATE SCHEMA auth;CREATE TABLE auth.users(id uuid PRIMARY KEY);CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$;
CREATE TABLE folders(id uuid PRIMARY KEY,user_id uuid,kind text);CREATE SCHEMA storage;
CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);`);
for(const file of ['20261029090000_agent_journals.sql','20261105130000_agent_history_search.sql','20261106233000_history_session_prefix.sql'])
 await db.exec(fs.readFileSync(new URL('../../../supabase/migrations/'+file,import.meta.url),'utf8'));
const owner='11111111-1111-4111-8111-111111111111',other='11111111-1111-4111-8111-111111111112',folder='22222222-2222-4222-8222-222222222222';
await db.query('INSERT INTO auth.users VALUES($1),($2)',[owner,other]);
await db.query("INSERT INTO folders VALUES($1,$2,'repo')",[folder,owner]);
const call=async(name,args)=>(await db.query(`SELECT ${name}(${args.map((_,i)=>'$'+(i+1)).join(',')}) AS value`,args)).rows[0].value;
const entry=(id,time,body,title='Investigate retention')=>({entry_id:id,agent:'codex',session_id:'native',captured_at:time,title,summary:'Observed cache eviction.',body});
const publish=async(day,sha,entries,rev=0)=>call('publish_searchable_agent_journal',[owner,folder,day,rev,'path/'+sha,sha,entries.length,['codex'],entries[0].captured_at,entries.at(-1).captured_at,JSON.stringify(entries)]);
await publish('2026-10-29','a',[entry('1','2026-10-29T23:00:00Z','Inspected decoder buffers.')]);
await publish('2026-11-04','b',[entry('2','2026-11-04T23:00:00Z','Memory growth follows cache retention.'),entry('3','2026-11-04T23:30:00Z','Validated memory is stable.')]);
const search=(pattern='',fields='all',first=null,last=null,agent=null,session=null,user=owner,limit=20,offset=0)=>call('search_agent_history',[user,folder,pattern,fields,first,last,agent,session,'UTC',limit,offset,'memory']);
let result=await search('memory');assert.equal(result.total_sessions,1);assert.equal(result.total_entries,2);assert.equal(result.sessions[0].entry_count,3);assert.equal(result.sessions[0].title_match,false);assert.equal(result.sessions[0].matches.length,2);assert.deepEqual(result.sessions[0].matching_dates,['2026-11-04']);
assert.equal((await search('decoder')).sessions[0].matches[0].date,'2026-10-29');
assert.equal((await search('decoder','title')).total_sessions,0);
result=await search('retention','title');assert.equal(result.total_entries,0);assert.equal(result.sessions[0].title_match,true);
assert.equal((await search('memory','all','2026-10-29','2026-10-29')).total_sessions,0);
assert.equal((await search('','all',null,null,'claude_code')).total_sessions,0);
assert.equal((await search('','all',null,null,null,'wrong')).total_sessions,0);
assert.equal((await search('','all',null,null,null,'nat')).total_sessions,1);
assert.equal((await search('','all',null,null,null,'ativ')).total_sessions,0);
assert.equal((await search('','all',null,null,null,'n_t')).total_sessions,0);
assert.equal((await search('','all',null,null,null,'nat',other)).total_sessions,0);
assert.equal((await search('','all',null,null,null,null,other)).total_sessions,0);
assert.equal((await search('(?=.*cache)(?=.*retention).*')).total_entries,1);
assert.equal((await search('memory|decoder')).total_entries,3);
assert.equal((await publish('2026-11-04','stale',[entry('bad','2026-11-04T23:30:00Z','wrong')],0)).status,'conflict');
assert.equal((await search('wrong')).total_sessions,0);
assert.equal(await call('index_agent_journal',[owner,folder,'2026-11-04','stale','[]']),false);
assert.equal((await search()).coverage.pending_days,0);
// New sessions paginate once, with stable native identity, not once per entry.
await publish('2026-11-05','c',[{...entry('4','2026-11-05T00:30:00Z','x'.repeat(1200)+' memory near the end.'),session_id:'second'}]);
result=await search('memory','all',null,null,null,null,owner,1,0);
assert.equal(result.total_sessions,2);assert.equal(result.has_more,true);
assert.ok(result.sessions[0].matches[0].excerpt.includes('memory near the end'));
const local=await call('search_agent_history',[owner,folder,'memory','all','2026-11-04','2026-11-04',null,'second','America/New_York',20,0,'memory']);
assert.deepEqual(local.sessions[0].matching_dates,['2026-11-04']);
const next=await search('memory','all',null,null,null,null,owner,1,1);
assert.equal(next.sessions.length,1);assert.notEqual(next.sessions[0].session_id,result.sessions[0].session_id);
// Existing writers invalidate index coverage until bounded backfill catches up.
await call('publish_agent_journal',[owner,folder,'2026-11-05',1,'path/d','d',1,['codex'],'2026-11-05T00:30:00Z','2026-11-05T00:30:00Z']);
assert.equal((await search('memory')).coverage.pending_days,1);
assert.equal((await search('memory')).total_sessions,1);
const pending=await call('pending_agent_journal_search',[owner,folder,1]);assert.equal(pending.remaining_days,1);assert.equal(pending.days.length,1);
for(const signature of ['search_agent_history(uuid,uuid,text,text,date,date,text,text,text,integer,integer,text)','index_agent_journal(uuid,uuid,date,text,jsonb)','pending_agent_journal_search(uuid,uuid,integer)']) {
 const p=(await db.query("SELECT has_function_privilege('authenticated',$1,'EXECUTE') a,has_function_privilege('anon',$1,'EXECUTE') n,has_function_privilege('service_role',$1,'EXECUTE') s",[signature])).rows[0];assert.equal(p.a,false);assert.equal(p.n,false);assert.equal(p.s,true);
}
await db.exec(`SET ROLE authenticated;SET request.jwt.claim.sub='${other}';`);
assert.equal((await db.query('SELECT * FROM agent_journal_search_entries')).rows.length,0);
console.log('History search SQL: grouping, title/body truth, dates, literal/regex, CAS, tenant isolation and grants passed');await db.close();
