-- Disposable database only; run after V1 acceptance fixtures and V2 migration.
do $$ begin
 if (select count(*) from access_credentials)<>(select count(*) from access_bindings) then raise exception 'legacy backfill lost variants'; end if;
 if exists(select 1 from access_credentials c join access_bindings b on b.id=c.legacy_binding_id where c.provider_ref is distinct from b.provider_ref or c.revision<>b.revision or c.write_operation_id is distinct from b.write_operation_id) then raise exception 'legacy reference changed'; end if;
 if has_table_privilege('authenticated','access_credentials','SELECT') or has_table_privilege('anon','credential_write_operations','SELECT') or has_function_privilege('authenticated','reserve_credential_write(uuid,uuid,uuid,uuid,integer,text,text,timestamptz,text)','EXECUTE') then raise exception 'raw access granted'; end if;
end $$;
insert into access_bindings(id,user_id,root_folder_id,resource_id,consumer,field_mapping,provider_ref,has_secret) values('40000000-0000-4000-8000-000000000002','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000001','other-app','{"OTHER_URI":"other"}','different-opaque',true);
do $$ begin
 if (select count(*) from access_credentials)<>2 then raise exception 'duplicate resource variants merged'; end if;
 if (select count(*) from secret_usage_grants)<>1 then raise exception 'new legacy variant inherited grants'; end if;
 update secret_grants set revoked_at=now();
 if exists(select 1 from secret_usage_grants where revoked_at is null) then raise exception 'legacy revocation not synchronized'; end if;
end $$;
insert into access_credentials(id,user_id,root_folder_id,resource_id,label,kind,fields) values('80000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000001','direct credential no mapping','uri','["connection"]');
do $$ declare r jsonb; v integer; expiry timestamptz:=now()+interval '1 day'; begin
 r:=reserve_credential_write('90000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','80000000-0000-4000-8000-000000000001',1,'v2-opaque','hmac-input',expiry,'public-fingerprint');
 if r->>'status'<>'pending' then raise exception 'V2 reservation failed'; end if;
 begin
 perform reserve_credential_write('90000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','80000000-0000-4000-8000-000000000001',1,'v2-opaque','different-input',expiry,null);
 raise exception 'changed idempotency payload accepted';
 exception when others then if sqlerrm<>'binding_changed' then raise; end if; end;
 begin
 perform reserve_credential_write('90000000-0000-4000-8000-000000000002','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','80000000-0000-4000-8000-000000000001',1,'v2-opaque-2','hmac-input2',null,null);
 raise exception 'overlapping write accepted';
 exception when others then if sqlerrm<>'binding_changed' then raise; end if; end;
 v:=finish_credential_write('90000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001');
 if v<>2 then raise exception 'V2 revision not advanced'; end if;
 v:=finish_credential_write('90000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001');
 if v<>2 or (select credential_expires_at from access_credentials where id='80000000-0000-4000-8000-000000000001')<>expiry then raise exception 'V2 retry/expiry failed'; end if;
 r:=reserve_credential_write('90000000-0000-4000-8000-000000000003','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','80000000-0000-4000-8000-000000000001',2,'v2-opaque-3','hmac-input3',null,null);
 v:=cancel_credential_write('90000000-0000-4000-8000-000000000003','10000000-0000-4000-8000-000000000001');
 if v<>3 then raise exception 'V2 cancellation did not invalidate revision'; end if;
 begin
 perform finish_credential_write('90000000-0000-4000-8000-000000000003','10000000-0000-4000-8000-000000000001');
 raise exception 'late finalize after cancellation accepted';
 exception when others then if sqlerrm<>'binding_changed' then raise; end if; end;
 if (select provider_ref from access_credentials where id='80000000-0000-4000-8000-000000000001')<>'v2-opaque' then raise exception 'cancel changed live reference'; end if;
end $$;
select 'V2 migration, reference preservation, no grant widening, immutable write and recovery acceptance passed' as result;
