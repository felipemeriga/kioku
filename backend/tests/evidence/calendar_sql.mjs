import {createRequire} from 'node:module';
import fs from 'node:fs';
const require=createRequire(import.meta.url);
const {PGlite}=require(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db=new PGlite();
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role;
CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$ SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
CREATE TABLE folders(id uuid PRIMARY KEY,user_id uuid,kind text); CREATE SCHEMA storage;
CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint);
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon,authenticated;`);
for(const file of ['20261105090000_agent_evidence.sql','20261105100000_agent_evidence_empty_attachments.sql','20261105103000_agent_evidence_rpc_privileges.sql','20261105120000_agent_history_calendar.sql','20261105123000_agent_history_bounded_children.sql'])
 await db.exec(fs.readFileSync(new URL('../../../supabase/migrations/'+file,import.meta.url),'utf8'));
const user='11111111-1111-4111-8111-111111111111',other='11111111-1111-4111-8111-111111111112',folder='22222222-2222-4222-8222-222222222222';
const ids=Array.from({length:6},(_,n)=>'33333333-3333-4333-8333-'+String(n+1).padStart(12,'0'));
await db.query('INSERT INTO auth.users VALUES($1),($2)',[user,other]);
await db.query("INSERT INTO folders VALUES($1,$2,'repo')",[folder,user]);
for(let i=0;i<ids.length;i++) {
 const root=i===1?ids[0]:i===3?ids[2]:ids[i],parent=[1,3].includes(i)?root:null;
 await db.query(`INSERT INTO agent_evidence_sessions(id,user_id,folder_id,agent,native_session_id,root_session_id,parent_session_id)
 VALUES($1,$2,$3,$4,$5,$6,$7)`,[ids[i],i===5?other:user,folder,i===4?'claude_code':'codex','native-'+i,root,parent]);
 await db.query(`INSERT INTO agent_evidence_objects(session_id,user_id,folder_id,object_id,descriptor,producer_id,stream_id,generation,kind,sha256,byte_length,committed_revision)
 VALUES($1,$2,$3,'obj','{"first_record":1}','pc','s',1,'segment',repeat('a',64),3,1)`,[ids[i],i===5?other:user,folder]);
}
let seq=0;
async function event(i,time,{visible=true,inherited=false}={}) {
 seq++;
 await db.query(`INSERT INTO agent_evidence_events(session_id,user_id,folder_id,event_id,object_id,stream_id,generation,record_sequence,byte_offset,byte_length,event_at,role,event_type,content_preview,displayable,inherited,parser_version)
 VALUES($1,$2,$3,$4,'obj','s',1,$5,0,3,$6,'user','message','sanitized', $7,$8,1)`,[ids[i],i===5?other:user,folder,String(seq).padStart(64,'0'),seq,time,visible,inherited]);
 return String(seq).padStart(64,'0');
}
await event(0,'2026-03-08T04:59:59Z'); // New York March7
await event(0,'2026-03-08T05:00:00Z'); // March8 midnight
await event(1,'2026-03-09T03:59:59Z'); // March8 end, DST23-hour day
await event(1,'2026-03-09T04:00:00Z'); // March9 midnight
const childAnchor=await event(3,'2026-03-08T06:00:00Z');
await event(4,'2026-03-08T07:00:00Z');
await event(5,'2026-03-08T07:00:00Z');
await event(0,'2026-03-08T08:00:00Z',{visible:false});
await event(1,'2026-03-08T08:00:00Z',{inherited:true});
const call=async(name,args)=>(await db.query(`SELECT ${name}(${args.map((_,i)=>'$'+(i+1)).join(',')}) AS value`,args)).rows[0].value;
const days=await call('agent_history_days',[user,folder,'2026-03-07','2026-03-09','America/New_York',null]);
if(days.length!==3||days[1].event_count!==4||days[1].session_count!==3||days[1].agents.join(',')!=='claude_code,codex')throw Error('DST/root counts '+JSON.stringify(days));
await db.query(`INSERT INTO agent_evidence_sessions(id,user_id,folder_id,agent,native_session_id,root_session_id,parent_session_id)
 SELECT ('44444444-4444-4444-8444-'||lpad(n::text,12,'0'))::uuid,$1,$2,'codex','bounded-child-'||n,$3,$3
 FROM generate_series(1,105) n`,[user,folder,ids[0]]);
const page=await call('agent_history_sessions',[user,folder,'2026-03-08','America/New_York',10,null,null,null]);
if(page.find(x=>x.id===ids[0]).children.length!==100)throw Error('unbounded child metadata');
if(page.length!==3||page.find(x=>x.id===ids[0]).day_event_count!==2)throw Error('root dedupe');
const child=page.find(x=>x.id===ids[2]);
if(child.day_first_session_id!==ids[3]||child.day_first_event_id!==childAnchor||child.native_session_id!=='native-2')throw Error('child-only anchor');
const filtered=await call('agent_history_days',[user,folder,'2026-03-08','2026-03-08','America/New_York','codex']);
if(filtered[0].event_count!==3||filtered[0].session_count!==2)throw Error('agent scope');
const first=await call('agent_history_sessions',[user,folder,'2026-03-08','America/New_York',1,null,null,null]);
const next=await call('agent_history_sessions',[user,folder,'2026-03-08','America/New_York',1,first[0].day_last_event_at,first[0].id,null]);
if(next.length!==1||next[0].id===first[0].id)throw Error('keyset pagination');
if((await call('agent_history_sessions',[user,folder,'2026-03-10','America/New_York',10,null,null,null])).length)throw Error('empty day');
if((await call('agent_history_days',[user,'22222222-2222-4222-8222-222222222223','2026-03-08','2026-03-08','UTC',null])).length)throw Error('folder scope');
await db.query('UPDATE agent_evidence_sessions SET deleted_at=now() WHERE id=$1',[ids[3]]);
const afterDelete=await call('agent_history_days',[user,folder,'2026-03-08','2026-03-08','America/New_York',null]);
if(afterDelete[0].session_count!==2)throw Error('deleted child included');
for(const signature of ['agent_history_days(uuid,uuid,date,date,text,text)','agent_history_sessions(uuid,uuid,date,text,integer,timestamptz,uuid,text)']) {
 const p=(await db.query("SELECT has_function_privilege('authenticated',$1,'EXECUTE') a,has_function_privilege('anon',$1,'EXECUTE') n,has_function_privilege('service_role',$1,'EXECUTE') s",[signature])).rows[0];
 if(p.a||p.n||!p.s)throw Error('calendar role grants');
}
console.log('Calendar PostgreSQL: DST, inclusive dates, root/child counts/anchors, filtering, pagination, deleted scope and grants passed');
await db.close();
