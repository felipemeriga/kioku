-- Additive V2 metadata only. Existing V1 tables, IDs and execution remain intact.
alter table public.access_resources add column environment_ids jsonb not null default '[]';
alter table public.access_resources add column credential_kind text not null default 'fields' check(credential_kind in ('uri','api_key','ssh','fields','aws'));
alter table public.access_resources add column credential_fields jsonb not null default '["connection"]';

create table public.access_credentials (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 resource_id uuid not null references public.access_resources(id) on delete cascade,
 environment_id uuid references public.root_environments(id) on delete restrict,
 label text not null default '' check(length(label)<=120),
 region text not null default '' check(length(region)<=120),
 kind text not null check(kind in ('uri','api_key','ssh','fields','aws')),
 fields jsonb not null check(jsonb_typeof(fields)='array' and jsonb_array_length(fields) between 1 and 32),
 enabled boolean not null default true, revision integer not null default 1 check(revision>0),
 provider_ref text, has_secret boolean not null default false,
 credential_expires_at timestamptz, write_operation_id uuid, fingerprint text,
 legacy_binding_id uuid unique references public.access_bindings(id) on delete cascade,
 created_at timestamptz not null default now()
);
-- No resource/environment unique constraint: legacy variants are independent secrets.
create table public.access_usages (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 credential_id uuid not null references public.access_credentials(id) on delete cascade,
 name text not null check(length(name) between 1 and 120),
 consumer text not null check(length(consumer) between 1 and 240),
 delivery jsonb not null check(jsonb_typeof(delivery)='object'),
 enabled boolean not null default true, revision integer not null default 1 check(revision>0),
 legacy_binding_id uuid unique references public.access_bindings(id) on delete cascade,
 created_at timestamptz not null default now()
);
create table public.secret_usage_grants (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 device_id uuid not null references public.secret_devices(id) on delete cascade,
 usage_id uuid not null references public.access_usages(id) on delete cascade,
 usage_revision integer not null check(usage_revision>0),
 allowed_fields jsonb not null, capabilities jsonb not null,
 expires_at timestamptz, revoked_at timestamptz,
 legacy_grant_id uuid unique references public.secret_grants(id) on delete cascade,
 created_at timestamptz not null default now(), unique(device_id,usage_id)
);
create table public.credential_write_operations (
 id uuid primary key, user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 credential_id uuid not null references public.access_credentials(id) on delete cascade,
 expected_revision integer not null, provider_ref text not null, input_hmac text not null,
 credential_expires_at timestamptz, fingerprint text,
 status text not null default 'pending' check(status in ('pending','complete','cancelled')),
 created_at timestamptz not null default now()
);
alter table public.secret_access_events add column credential_id uuid references public.access_credentials(id) on delete set null;
alter table public.secret_access_events add column usage_id uuid references public.access_usages(id) on delete set null;
create index on public.access_credentials(root_folder_id);
create index on public.access_usages(root_folder_id);
create index on public.secret_usage_grants(device_id);
do $$ declare t text; begin
 foreach t in array array['access_credentials','access_usages','secret_usage_grants','credential_write_operations'] loop
 execute format('alter table public.%I enable row level security',t);
 execute format('revoke all on public.%I from public, anon, authenticated',t);
 execute format('grant all on public.%I to service_role',t);
 end loop;
end $$;

-- One variant per old binding; opaque references only. Never read/copy provider values.
insert into public.access_credentials(id,user_id,root_folder_id,resource_id,environment_id,label,kind,fields,enabled,revision,provider_ref,has_secret,credential_expires_at,write_operation_id,legacy_binding_id)
select b.id,b.user_id,b.root_folder_id,b.resource_id,b.environment_id,b.consumer,'fields',
 (select jsonb_agg(distinct v) from jsonb_each_text(b.field_mapping) m(k,v)),b.enabled,b.revision,b.provider_ref,b.has_secret,b.credential_expires_at,b.write_operation_id,b.id
from public.access_bindings b;
insert into public.access_usages(id,user_id,root_folder_id,credential_id,name,consumer,delivery,enabled,revision,legacy_binding_id)
select id,user_id,root_folder_id,id,consumer,consumer,jsonb_build_object('kind','env','field_mapping',field_mapping,'clear_env',clear_env),enabled,revision,id from public.access_bindings;
insert into public.secret_usage_grants(id,user_id,root_folder_id,device_id,usage_id,usage_revision,allowed_fields,capabilities,expires_at,revoked_at,legacy_grant_id)
select g.id,g.user_id,g.root_folder_id,g.device_id,g.binding_id,b.revision,
 (select jsonb_agg(distinct v) from jsonb_each_text(b.field_mapping) m(k,v)), '["env"]',g.expires_at,g.revoked_at,g.id
from public.secret_grants g join public.access_bindings b on b.id=g.binding_id;
update public.access_resources r set environment_ids=coalesce((select jsonb_agg(distinct b.environment_id) from public.access_bindings b where b.resource_id=r.id and b.environment_id is not null),'[]');

-- Future V1 clients remain live. Synchronization preserves each independent ID/reference.
create function public.sync_legacy_access_binding() returns trigger language plpgsql security definer set search_path=public,pg_temp as $$
begin
 insert into public.access_credentials(id,user_id,root_folder_id,resource_id,environment_id,label,kind,fields,enabled,revision,provider_ref,has_secret,credential_expires_at,write_operation_id,legacy_binding_id)
 values(new.id,new.user_id,new.root_folder_id,new.resource_id,new.environment_id,new.consumer,'fields',(select jsonb_agg(distinct v) from jsonb_each_text(new.field_mapping) m(k,v)),new.enabled,new.revision,new.provider_ref,new.has_secret,new.credential_expires_at,new.write_operation_id,new.id)
 on conflict(id) do update set label=excluded.label,fields=excluded.fields,enabled=excluded.enabled,revision=excluded.revision,provider_ref=excluded.provider_ref,has_secret=excluded.has_secret,credential_expires_at=excluded.credential_expires_at,write_operation_id=excluded.write_operation_id;
 insert into public.access_usages(id,user_id,root_folder_id,credential_id,name,consumer,delivery,enabled,revision,legacy_binding_id)
 values(new.id,new.user_id,new.root_folder_id,new.id,new.consumer,new.consumer,jsonb_build_object('kind','env','field_mapping',new.field_mapping,'clear_env',new.clear_env),new.enabled,new.revision,new.id)
 on conflict(id) do update set name=excluded.name,consumer=excluded.consumer,delivery=excluded.delivery,enabled=excluded.enabled,revision=excluded.revision;
 return new;
end $$;
create trigger sync_legacy_access_binding after insert or update on public.access_bindings for each row execute function public.sync_legacy_access_binding();
create function public.sync_legacy_secret_grant() returns trigger language plpgsql security definer set search_path=public,pg_temp as $$
declare b public.access_bindings;
begin
 select * into b from public.access_bindings where id=new.binding_id;
 insert into public.secret_usage_grants(id,user_id,root_folder_id,device_id,usage_id,usage_revision,allowed_fields,capabilities,expires_at,revoked_at,legacy_grant_id)
 values(new.id,new.user_id,new.root_folder_id,new.device_id,new.binding_id,b.revision,(select jsonb_agg(distinct v) from jsonb_each_text(b.field_mapping) m(k,v)),'["env"]',new.expires_at,new.revoked_at,new.id)
 on conflict(device_id,usage_id) do update set revoked_at=excluded.revoked_at,expires_at=excluded.expires_at;
 return new;
end $$;
create trigger sync_legacy_secret_grant after insert or update on public.secret_grants for each row execute function public.sync_legacy_secret_grant();

create function public.reserve_credential_write(p_id uuid,p_owner uuid,p_root uuid,p_credential uuid,p_revision integer,p_ref text,p_digest text,p_expiry timestamptz,p_fingerprint text)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare c public.access_credentials; op public.credential_write_operations;
begin
 select * into c from public.access_credentials where id=p_credential and user_id=p_owner and root_folder_id=p_root for update;
 if not found or c.legacy_binding_id is not null then raise exception 'access_denied'; end if;
 select * into op from public.credential_write_operations where id=p_id;
 if found then
 if op.user_id<>p_owner or op.root_folder_id<>p_root or op.credential_id<>p_credential or op.expected_revision<>p_revision or op.input_hmac<>p_digest then raise exception 'binding_changed'; end if;
 return jsonb_build_object('status',op.status,'provider_ref',op.provider_ref);
 end if;
 if c.revision<>p_revision or c.write_operation_id is not null then raise exception 'binding_changed'; end if;
 insert into public.credential_write_operations(id,user_id,root_folder_id,credential_id,expected_revision,provider_ref,input_hmac,credential_expires_at,fingerprint) values(p_id,p_owner,p_root,p_credential,p_revision,p_ref,p_digest,p_expiry,p_fingerprint);
 update public.access_credentials set write_operation_id=p_id where id=c.id;
 return jsonb_build_object('status','pending','provider_ref',p_ref);
end $$;
create function public.finish_credential_write(p_id uuid,p_owner uuid) returns integer language plpgsql security definer set search_path=public,pg_temp as $$
declare op public.credential_write_operations; v integer;
begin
 select * into op from public.credential_write_operations where id=p_id and user_id=p_owner for update;
 if not found then raise exception 'access_denied'; end if;
 if op.status='complete' then return op.expected_revision+1; end if;
 if op.status<>'pending' then raise exception 'binding_changed'; end if;
 update public.access_credentials set provider_ref=op.provider_ref,has_secret=true,revision=revision+1,credential_expires_at=op.credential_expires_at,fingerprint=op.fingerprint,write_operation_id=null
 where id=op.credential_id and user_id=p_owner and root_folder_id=op.root_folder_id and revision=op.expected_revision and write_operation_id=op.id returning revision into v;
 if v is null then raise exception 'binding_changed'; end if;
 update public.credential_write_operations set status='complete' where id=op.id;
 return v;
end $$;
create function public.cancel_credential_write(p_id uuid,p_owner uuid) returns integer language plpgsql security definer set search_path=public,pg_temp as $$
declare op public.credential_write_operations; v integer;
begin
 select * into op from public.credential_write_operations where id=p_id and user_id=p_owner for update;
 if not found then raise exception 'access_denied'; end if;
 if op.status<>'pending' then raise exception 'binding_changed'; end if;
 update public.access_credentials set write_operation_id=null,revision=revision+1 where id=op.credential_id and user_id=p_owner and root_folder_id=op.root_folder_id and revision=op.expected_revision and write_operation_id=op.id returning revision into v;
 if v is null then raise exception 'binding_changed'; end if;
 update public.credential_write_operations set status='cancelled' where id=op.id;
 return v;
end $$;
revoke all on function public.sync_legacy_access_binding() from public,anon,authenticated;
revoke all on function public.sync_legacy_secret_grant() from public,anon,authenticated;
revoke all on function public.reserve_credential_write(uuid,uuid,uuid,uuid,integer,text,text,timestamptz,text) from public,anon,authenticated;
revoke all on function public.finish_credential_write(uuid,uuid) from public,anon,authenticated;
revoke all on function public.cancel_credential_write(uuid,uuid) from public,anon,authenticated;
grant execute on function public.reserve_credential_write(uuid,uuid,uuid,uuid,integer,text,text,timestamptz,text) to service_role;
grant execute on function public.finish_credential_write(uuid,uuid) to service_role;
grant execute on function public.cancel_credential_write(uuid,uuid) to service_role;
