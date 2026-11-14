-- Secret values live exclusively in Infisical. These tables contain metadata.
create table public.root_access_guides (
 root_folder_id uuid primary key references public.folders(id) on delete cascade,
 user_id uuid not null references auth.users(id) on delete cascade,
 markdown text not null default '' check (octet_length(markdown) <= 65536),
 revision integer not null default 1 check(revision > 0),
 updated_at timestamptz not null default now()
);
create table public.root_environments (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 name text not null check(length(name) between 1 and 120), slug text not null check(slug ~ '^[a-z][a-z0-9-]{0,39}$'),
 sensitivity text not null default 'normal' check(sensitivity in ('normal','production')),
 created_at timestamptz not null default now(), unique(root_folder_id,slug)
);
create table public.access_resources (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 name text not null check(length(name) between 1 and 120), description text not null default '',
 type text not null check(type in ('database','observability','cloud','other')),
 aliases jsonb not null default '[]', shared boolean not null default false,
 account text not null default '', region text not null default '', created_at timestamptz not null default now(),
 unique(root_folder_id,name)
);
create table public.access_bindings (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 resource_id uuid not null references public.access_resources(id) on delete cascade,
 environment_id uuid references public.root_environments(id) on delete restrict,
 consumer text not null check(length(consumer) between 1 and 120),
 field_mapping jsonb not null, clear_env jsonb not null default '[]',
 revision integer not null default 1 check(revision>0), enabled boolean not null default true,
 provider_ref text, has_secret boolean not null default false,
 credential_expires_at timestamptz, write_operation_id uuid, created_at timestamptz not null default now()
);
create table public.secret_devices (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 label text not null check(length(label) between 1 and 120), credential_hash text not null unique,
 created_at timestamptz not null default now(), last_used_at timestamptz,
 expires_at timestamptz not null, revoked_at timestamptz
);
create table public.secret_grants (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 device_id uuid not null references public.secret_devices(id) on delete cascade,
 binding_id uuid not null references public.access_bindings(id) on delete cascade,
 expires_at timestamptz, revoked_at timestamptz, created_at timestamptz not null default now(),
 unique(device_id,binding_id)
);
create table public.secret_access_enrollments (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 label text not null, code_hash text not null unique, status text not null default 'pending' check(status in ('pending','approved','denied','consumed')),
 binding_ids jsonb not null default '[]', created_at timestamptz not null default now(), expires_at timestamptz not null
);
create table public.secret_write_operations (
 id uuid primary key, user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 binding_id uuid not null references public.access_bindings(id) on delete cascade,
 expected_revision integer not null, provider_ref text not null, input_hmac text not null, credential_expires_at timestamptz,
 status text not null default 'pending' check(status in ('pending','complete','cancelled')),
 created_at timestamptz not null default now()
);
create table public.secret_access_events (
 id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 device_id uuid references public.secret_devices(id) on delete set null,
 resource_id uuid references public.access_resources(id) on delete set null,
 binding_id uuid references public.access_bindings(id) on delete set null,
 invocation_id uuid, action text not null, outcome text not null,
 created_at timestamptz not null default now()
);
create index on public.secret_access_events(root_folder_id,created_at desc);
create index on public.access_bindings(root_folder_id);
create index on public.secret_devices(root_folder_id);
-- No direct authenticated writes: enforce relationships and secret isolation in backend.
do $$ declare t text; begin
 foreach t in array array['root_access_guides','root_environments','access_resources','access_bindings','secret_devices','secret_grants','secret_access_enrollments','secret_write_operations','secret_access_events'] loop
 execute format('alter table public.%I enable row level security',t);
 execute format('revoke all on public.%I from anon, authenticated',t);
 execute format('grant all on public.%I to service_role',t);
 end loop;
end $$;

-- A single successful poll creates device and grants, without storing plaintext token.
create function public.consume_secret_enrollment(p_request uuid,p_code_hash text,p_device uuid,p_credential_hash text)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare e public.secret_access_enrollments; b uuid; expiry timestamptz := now()+interval '30 days';
begin
 select * into e from public.secret_access_enrollments where id=p_request and code_hash=p_code_hash for update;
 if not found or e.expires_at<=now() then return jsonb_build_object('status','expired'); end if;
 if e.status<>'approved' then return jsonb_build_object('status',e.status); end if;
 if not exists(select 1 from public.folders where id=e.root_folder_id and user_id=e.user_id and parent_id is null) then return jsonb_build_object('status','denied'); end if;
 insert into public.secret_devices(id,user_id,root_folder_id,label,credential_hash,expires_at) values(p_device,e.user_id,e.root_folder_id,e.label,p_credential_hash,expiry);
 for b in select jsonb_array_elements_text(e.binding_ids)::uuid loop
 if not exists(select 1 from public.access_bindings where id=b and user_id=e.user_id and root_folder_id=e.root_folder_id and enabled) then raise exception 'binding_changed'; end if;
 insert into public.secret_grants(user_id,root_folder_id,device_id,binding_id) values(e.user_id,e.root_folder_id,p_device,b);
 end loop;
 update public.secret_access_enrollments set status='consumed' where id=e.id;
 return jsonb_build_object('status','approved','device_id',p_device,'root_id',e.root_folder_id,'expires_at',expiry);
end $$;
revoke all on function public.consume_secret_enrollment(uuid,text,uuid,text) from public,anon,authenticated;
grant execute on function public.consume_secret_enrollment(uuid,text,uuid,text) to service_role;

-- Reserve a binding before vault I/O, making uncertain writes fail closed.
create function public.reserve_secret_write(p_id uuid,p_owner uuid,p_root uuid,p_binding uuid,p_revision integer,p_ref text,p_digest text,p_expiry timestamptz)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare b public.access_bindings; op public.secret_write_operations;
begin
 select * into b from public.access_bindings where id=p_binding and user_id=p_owner and root_folder_id=p_root for update;
 if not found then raise exception 'access_denied'; end if;
 select * into op from public.secret_write_operations where id=p_id;
 if found then
 if op.user_id<>p_owner or op.root_folder_id<>p_root or op.binding_id<>p_binding or op.expected_revision<>p_revision or op.input_hmac<>p_digest then raise exception 'binding_changed'; end if;
 return jsonb_build_object('status',op.status,'provider_ref',op.provider_ref);
 end if;
 if b.revision<>p_revision or b.write_operation_id is not null then raise exception 'binding_changed'; end if;
 insert into public.secret_write_operations(id,user_id,root_folder_id,binding_id,expected_revision,provider_ref,input_hmac,credential_expires_at) values(p_id,p_owner,p_root,p_binding,p_revision,p_ref,p_digest,p_expiry);
 update public.access_bindings set write_operation_id=p_id where id=b.id;
 return jsonb_build_object('status','pending','provider_ref',p_ref);
end $$;
create function public.finish_secret_write(p_id uuid,p_owner uuid,p_expiry timestamptz)
returns integer language plpgsql security definer set search_path=public,pg_temp as $$
declare op public.secret_write_operations; v integer;
begin
 select * into op from public.secret_write_operations where id=p_id and user_id=p_owner for update;
 if not found then raise exception 'access_denied'; end if;
 if op.status='complete' then return op.expected_revision+1; end if;
 if op.status<>'pending' then raise exception 'binding_changed'; end if;
 update public.access_bindings set provider_ref=op.provider_ref,has_secret=true,revision=revision+1,credential_expires_at=op.credential_expires_at,write_operation_id=null
 where id=op.binding_id and user_id=p_owner and root_folder_id=op.root_folder_id and revision=op.expected_revision and write_operation_id=op.id returning revision into v;
 if v is null then raise exception 'binding_changed'; end if;
 update public.secret_write_operations set status='complete' where id=op.id;
 return v;
end $$;
revoke all on function public.reserve_secret_write(uuid,uuid,uuid,uuid,integer,text,text,timestamptz) from public,anon,authenticated;
revoke all on function public.finish_secret_write(uuid,uuid,timestamptz) from public,anon,authenticated;
grant execute on function public.reserve_secret_write(uuid,uuid,uuid,uuid,integer,text,text,timestamptz) to service_role;
grant execute on function public.finish_secret_write(uuid,uuid,timestamptz) to service_role;
create table public.root_access_guide_revisions (
 root_folder_id uuid not null references public.folders(id) on delete cascade,
 user_id uuid not null references auth.users(id) on delete cascade,
 revision integer not null, markdown text not null check(octet_length(markdown)<=65536),
 created_at timestamptz not null default now(), primary key(root_folder_id,revision)
);
alter table public.root_access_guide_revisions enable row level security;
revoke all on public.root_access_guide_revisions from anon,authenticated;
grant all on public.root_access_guide_revisions to service_role;
create function public.save_root_access_guide(p_owner uuid,p_root uuid,p_revision integer,p_markdown text)
returns integer language plpgsql security definer set search_path=public,pg_temp as $$
declare v integer;
begin
 perform 1 from public.folders where id=p_root and user_id=p_owner and parent_id is null for update;
 if not found then raise exception 'access_denied'; end if;
 if p_revision=0 then
 insert into public.root_access_guides(root_folder_id,user_id,revision,markdown) values(p_root,p_owner,1,p_markdown) on conflict do nothing returning revision into v;
 else
 update public.root_access_guides set markdown=p_markdown,revision=revision+1,updated_at=now() where root_folder_id=p_root and user_id=p_owner and revision=p_revision returning revision into v;
 end if;
 if v is null then raise exception 'binding_changed'; end if;
 insert into public.root_access_guide_revisions(root_folder_id,user_id,revision,markdown) values(p_root,p_owner,v,p_markdown);
 return v;
end $$;
revoke all on function public.save_root_access_guide(uuid,uuid,integer,text) from public,anon,authenticated;
grant execute on function public.save_root_access_guide(uuid,uuid,integer,text) to service_role;
create function public.cancel_secret_write(p_id uuid,p_owner uuid)
returns integer language plpgsql security definer set search_path=public,pg_temp as $$
declare op public.secret_write_operations; v integer;
begin
 select * into op from public.secret_write_operations where id=p_id and user_id=p_owner for update;
 if not found or op.status<>'pending' then raise exception 'binding_changed'; end if;
 update public.access_bindings set write_operation_id=null,revision=revision+1
 where id=op.binding_id and user_id=p_owner and root_folder_id=op.root_folder_id and revision=op.expected_revision and write_operation_id=op.id returning revision into v;
 if v is null then raise exception 'binding_changed'; end if;
 update public.secret_write_operations set status='cancelled' where id=op.id;
 return v;
end $$;
revoke all on function public.cancel_secret_write(uuid,uuid) from public,anon,authenticated;
grant execute on function public.cancel_secret_write(uuid,uuid) to service_role;
