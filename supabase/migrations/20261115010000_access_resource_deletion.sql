-- Resumable, provider-first resource deletion. Opaque references only.
alter table public.access_resources
 add column deletion_requested_at timestamptz,
 add column deletion_refs jsonb not null default '[]' check(jsonb_typeof(deletion_refs)='array');

-- Serialize writes with the deletion snapshot, including existing V1 RPCs.
create function public.guard_active_access_resource() returns trigger
language plpgsql security definer set search_path=public,pg_temp as $$
declare r public.access_resources;
begin
 select * into r from public.access_resources where id=new.resource_id for share;
 if not found or r.user_id<>new.user_id or r.root_folder_id<>new.root_folder_id
    or r.deletion_requested_at is not null then raise exception 'resource_deleting'; end if;
 return new;
end $$;
create trigger guard_active_access_binding before insert or update on public.access_bindings
 for each row execute function public.guard_active_access_resource();
create trigger guard_active_access_credential before insert or update on public.access_credentials
 for each row execute function public.guard_active_access_resource();

create function public.begin_access_resource_deletion(p_owner uuid,p_root uuid,p_resource uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare r public.access_resources; refs jsonb;
begin
 select * into r from public.access_resources where id=p_resource and user_id=p_owner and root_folder_id=p_root for update;
 if not found then raise exception 'access_denied'; end if;
 if r.deletion_requested_at is not null then return r.deletion_refs; end if;
 if exists(select 1 from public.access_bindings b where b.resource_id=r.id and b.write_operation_id is not null)
 or exists(select 1 from public.access_credentials c where c.resource_id=r.id and c.write_operation_id is not null)
 or exists(select 1 from public.secret_write_operations o join public.access_bindings b on b.id=o.binding_id where b.resource_id=r.id and o.status='pending')
 or exists(select 1 from public.credential_write_operations o join public.access_credentials c on c.id=o.credential_id where c.resource_id=r.id and o.status='pending')
 then raise exception 'resource_busy'; end if;
 select coalesce(jsonb_agg(distinct ref),'[]') into refs from (
  select provider_ref as ref from public.access_bindings where resource_id=r.id
  union select provider_ref from public.access_credentials where resource_id=r.id
  union select o.provider_ref from public.secret_write_operations o join public.access_bindings b on b.id=o.binding_id where b.resource_id=r.id
  union select o.provider_ref from public.credential_write_operations o join public.access_credentials c on c.id=o.credential_id where c.resource_id=r.id
 ) all_refs where ref is not null;
 -- Never remove a value also referenced by a different resource/owner.
 if exists(select 1 from public.access_bindings b where refs ? b.provider_ref and b.resource_id<>r.id)
 or exists(select 1 from public.access_credentials c where refs ? c.provider_ref and c.resource_id<>r.id)
 or exists(select 1 from public.secret_write_operations o join public.access_bindings b on b.id=o.binding_id where refs ? o.provider_ref and b.resource_id<>r.id)
 or exists(select 1 from public.credential_write_operations o join public.access_credentials c on c.id=o.credential_id where refs ? o.provider_ref and c.resource_id<>r.id)
 then raise exception 'resource_shared_reference'; end if;
 update public.access_resources set deletion_requested_at=now(),deletion_refs=refs where id=r.id;
 return refs;
end $$;

create function public.ack_access_resource_deletion(p_owner uuid,p_root uuid,p_resource uuid,p_ref text)
returns integer language plpgsql security definer set search_path=public,pg_temp as $$
declare remaining integer;
begin
 update public.access_resources set deletion_refs=deletion_refs-p_ref
 where id=p_resource and user_id=p_owner and root_folder_id=p_root and deletion_requested_at is not null
 returning jsonb_array_length(deletion_refs) into remaining;
 if remaining is null then raise exception 'access_denied'; end if;
 return remaining;
end $$;

create function public.finish_access_resource_deletion(p_owner uuid,p_root uuid,p_resource uuid)
returns void language plpgsql security definer set search_path=public,pg_temp as $$
declare r public.access_resources;
begin
 select * into r from public.access_resources where id=p_resource and user_id=p_owner and root_folder_id=p_root for update;
 if not found or r.deletion_requested_at is null or jsonb_array_length(r.deletion_refs)<>0 then raise exception 'resource_busy'; end if;
 insert into public.secret_access_events(user_id,root_folder_id,resource_id,action,outcome)
 values(p_owner,p_root,p_resource,'resource_deleted','allowed');
 delete from public.access_resources where id=r.id;
end $$;
revoke all on function public.guard_active_access_resource() from public,anon,authenticated;
revoke all on function public.begin_access_resource_deletion(uuid,uuid,uuid) from public,anon,authenticated;
revoke all on function public.ack_access_resource_deletion(uuid,uuid,uuid,text) from public,anon,authenticated;
revoke all on function public.finish_access_resource_deletion(uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function public.begin_access_resource_deletion(uuid,uuid,uuid) to service_role;
grant execute on function public.ack_access_resource_deletion(uuid,uuid,uuid,text) to service_role;
grant execute on function public.finish_access_resource_deletion(uuid,uuid,uuid) to service_role;
