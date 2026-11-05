import {createRequire} from 'node:module';
import fs from 'node:fs';
const require=createRequire(import.meta.url);
const {PGlite}=require(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db=new PGlite();
await db.exec(`CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role; CREATE SCHEMA auth; CREATE TABLE auth.users(id uuid PRIMARY KEY); CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS $$ SELECT nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$; CREATE TABLE folders(id uuid PRIMARY KEY,user_id uuid,kind text); CREATE SCHEMA storage; CREATE TABLE storage.buckets(id text PRIMARY KEY,name text,public boolean,file_size_limit bigint);`);
await db.exec(fs.readFileSync(new URL('../../../supabase/migrations/20261105090000_agent_evidence.sql',import.meta.url),'utf8'));
await db.exec(fs.readFileSync(new URL('../../../supabase/migrations/20261105100000_agent_evidence_empty_attachments.sql',import.meta.url),'utf8'));
const user='11111111-1111-4111-8111-111111111111', folder='22222222-2222-4222-8222-222222222222';
await db.query('INSERT INTO auth.users VALUES($1)',[user]); await db.query("INSERT INTO folders VALUES($1,$2,'repo')",[folder,user]);
const request={folder_id:folder,agent:'codex',native_session_id:'root',producer_id:'pc',batch_id:'first',base_revision:0,objects:[],gaps:[],lifecycle:{status:'observed'}};
const call=async(name,args)=> (await db.query(`SELECT ${name}(${args.map((_,i)=>'$'+(i+1)).join(',')}) AS value`,args)).rows[0].value;
const prepared=await call('prepare_agent_evidence',[user,request]);
const accepted=await call('commit_agent_evidence',[user,'first']);
if(accepted.revision!==1)throw Error(JSON.stringify(accepted));
const replay=await call('commit_agent_evidence',[user,'first']); if(replay.status!=='unchanged')throw Error('replay');
await call('prepare_agent_evidence',[user,{...request,batch_id:'stale'}]);
const stale=await call('commit_agent_evidence',[user,'stale']); if(stale.status!=='conflict')throw Error(JSON.stringify(stale));
// Empty attachments survive prepare, upload receipt and commit; zero segments fail SQL.
const emptyDescriptor={id:'empty',kind:'attachment',stream_id:'native',generation:1,sha256:'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',byte_length:0,original_name:'empty.txt'};
const emptySession=await call('prepare_agent_evidence',[user,{...request,native_session_id:'empty',batch_id:'empty',objects:[emptyDescriptor]}]);
const emptyLease=await call('claim_agent_evidence_upload',[user,emptySession.session_id,'empty']);
await call('finish_agent_evidence_upload',[user,emptySession.session_id,'empty',emptyLease.nonce,'empty/attachment']);
if((await call('commit_agent_evidence',[user,'empty'])).status!=='accepted')throw Error('empty attachment rejected');
let zeroSegmentRejected=false;
try {await db.query("UPDATE agent_evidence_objects SET kind='segment' WHERE session_id=$1",[emptySession.session_id]);}
catch {zeroSegmentRejected=true;}
if(!zeroSegmentRejected)throw Error('empty segment accepted');
// Independent producers serialize through CAS; gap snapshots replace, not append.
await call('prepare_agent_evidence',[user,{...request,batch_id:'second',base_revision:1,gaps:[{code:'attachment_missing',name:'a'}]}]);
await call('commit_agent_evidence',[user,'second']);
await call('prepare_agent_evidence',[user,{...request,batch_id:'resolved',base_revision:2}]);
await call('commit_agent_evidence',[user,'resolved']);
let root=(await db.query('SELECT * FROM agent_evidence_sessions WHERE id=$1',[prepared.session_id])).rows[0];
if(root.gaps.length)throw Error('resolved producer gap persisted');
const child=await call('prepare_agent_evidence',[user,{...request,native_session_id:'child',native_root_session_id:'root',native_parent_session_id:'root',batch_id:'child',base_revision:0}]);
await call('commit_agent_evidence',[user,'child']);
root=(await db.query('SELECT * FROM agent_evidence_sessions WHERE id=$1',[prepared.session_id])).rows[0];
if(root.manifest_json.children[0].id!==child.session_id)throw Error('child missing canonical manifest');
const descriptor={id:'obj',kind:'segment',stream_id:'s',generation:1,sha256:'a'.repeat(64),byte_length:3,source_start:0,source_end:3,first_record:1,last_record:1,record_count:1};
await call('prepare_agent_evidence',[user,{...request,native_session_id:'source',batch_id:'source',objects:[descriptor]}]);
const source=(await db.query("SELECT * FROM agent_evidence_sessions WHERE native_session_id='source'")).rows[0];
let missing=await call('commit_agent_evidence',[user,'source']);if(missing.status!=='incomplete')throw Error(JSON.stringify(missing));
const lease=await call('claim_agent_evidence_upload',[user,source.id,'obj']);
await call('finish_agent_evidence_upload',[user,source.id,'obj',lease.nonce,'test/source/segments/obj']);
await call('commit_agent_evidence',[user,'source']);
const event={event_id:'b'.repeat(64),stream_id:'s',generation:1,record_sequence:1,byte_offset:0,byte_length:3,event_at:'2026-11-04T00:00:00Z',role:'user',event_type:'message',content_preview:'hi',displayable:true};
await call('publish_agent_evidence_index',[source.id,'obj',[event],{},1,true]);
const indexed=(await db.query('SELECT * FROM agent_evidence_sessions WHERE id=$1',[source.id])).rows[0];
if(indexed.event_count!==1||indexed.indexed_revision!==1||indexed.index_generation!==1)throw Error('index publication');
// Authenticated users cannot read another owner, including via direct SQL.
await db.exec('GRANT USAGE ON SCHEMA public,auth TO authenticated; GRANT EXECUTE ON FUNCTION auth.uid() TO authenticated; SET ROLE authenticated;');
await db.query("SELECT set_config('request.jwt.claim.sub',$1,false)",['33333333-3333-4333-8333-333333333333']);
if((await db.query('SELECT * FROM agent_evidence_sessions')).rows.length)throw Error('RLS leak');
await db.exec('RESET ROLE');
// BEFORE DELETE outbox retains nested and metadata-only manifest keys.
await db.query('DELETE FROM agent_evidence_sessions WHERE id=$1',[source.id]);
const outbox=(await db.query('SELECT storage_paths FROM agent_evidence_purge_outbox')).rows;
if(!outbox.some(x=>x.storage_paths.includes('test/source/segments/obj')))throw Error('object purge lost');
await call('delete_agent_evidence',[user,folder,prepared.session_id]);
if(!(await db.query('SELECT deleted_at FROM agent_evidence_sessions WHERE id=$1',[child.session_id])).rows[0].deleted_at)throw Error('child tombstone lost');
let deleted=false;try{await call('prepare_agent_evidence',[user,{...request,batch_id:'resurrection'}]);}catch(e){deleted=String(e).includes('evidence_deleted');}if(!deleted)throw Error('resurrection');
// Independent SQL clients queued at the same base revision: exactly one wins.
const concurrent={...request,native_session_id:'race',base_revision:0};
await call('prepare_agent_evidence',[user,{...concurrent,batch_id:'race-a'}]);
await call('prepare_agent_evidence',[user,{...concurrent,batch_id:'race-b',producer_id:'other-pc'}]);
const raced=await Promise.all(['race-a','race-b'].map(id=>call('commit_agent_evidence',[user,id])));
if(raced.filter(r=>r.status==='accepted').length!==1||raced.filter(r=>r.status==='conflict').length!==1)throw Error('two CAS winners');
// A missing second object cannot partially publish the first descriptor.
const partial=await call('prepare_agent_evidence',[user,{...request,native_session_id:'partial',batch_id:'partial',objects:[descriptor,{...descriptor,id:'obj2',stream_id:'other'}]}]);
const partialLease=await call('claim_agent_evidence_upload',[user,partial.session_id,'obj']);
await call('finish_agent_evidence_upload',[user,partial.session_id,'obj',partialLease.nonce,'partial/body']);
if((await call('commit_agent_evidence',[user,'partial'])).status!=='incomplete')throw Error('partial accepted');
if((await db.query('SELECT committed_revision FROM agent_evidence_objects WHERE session_id=$1',[partial.session_id])).rows.some(r=>r.committed_revision!==null))throw Error('partial publication');
// Reverse insertion of >256 segments must select numeric predecessors before LIMIT.
const longSession=await call('prepare_agent_evidence',[user,{...request,native_session_id:'long',batch_id:'long'}]);
await db.query(`INSERT INTO agent_evidence_objects(session_id,user_id,folder_id,object_id,
  descriptor,producer_id,stream_id,generation,kind,sha256,byte_length,committed_revision)
  SELECT $1,$2,$3,'segment-'||n,jsonb_build_object('first_record',n,'last_record',n),
  'pc','native',1,'segment',repeat('a',64),3,1 FROM generate_series(600,1,-1) n`,
  [longSession.session_id,user,folder]);
let expected=1;
for(let page=0;page<3;page++) {
  const rows=(await db.query(`SELECT object_id,first_record FROM agent_evidence_objects
    WHERE session_id=$1 AND kind='segment' AND committed_revision IS NOT NULL
      AND indexed_parser_version<1 ORDER BY stream_id,generation,first_record LIMIT 256`,
    [longSession.session_id])).rows;
  if(!rows.length)throw Error('long indexing stalled');
  for(const row of rows) {if(row.first_record!==expected++)throw Error('numeric source ordering broken');}
  await db.query(`UPDATE agent_evidence_objects SET indexed_parser_version=1
    WHERE session_id=$1 AND object_id=ANY($2::text[])`,[longSession.session_id,rows.map(r=>r.object_id)]);
}
if(expected!==601)throw Error('long index did not fully drain');
// Cascade cleanup survives object-first FK deletion and includes planned unfinished uploads.
await call('claim_agent_evidence_upload',[user,partial.session_id,'obj2']);
const planned=(await db.query('SELECT storage_path FROM agent_evidence_objects WHERE session_id=$1',[partial.session_id])).rows.map(r=>r.storage_path);
await db.query('DELETE FROM auth.users WHERE id=$1',[user]);
const purge=(await db.query('SELECT storage_paths,not_before FROM agent_evidence_purge_outbox')).rows;
const paths=purge.flatMap(x=>x.storage_paths);
if(!planned.every(p=>paths.includes(p)))throw Error('cascade lost planned bodies');
if(!paths.some(p=>p.endsWith('/root/subagents/child/manifest.json')))throw Error('nested manifest lost');
if(!purge.every(p=>p.not_before))throw Error('inflight grace missing');
console.log('PostgreSQL WASM: CAS, replay, partial atomicity, gaps, ancestry, lease, index, RLS, cascade purge passed');
await db.close();
