-- Run after root-access migration against disposable fixtures (never production).
insert into auth.users(id) values ('10000000-0000-4000-8000-000000000001');
insert into public.folders(id,user_id,parent_id) values ('20000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001',null);
insert into public.access_resources(id,user_id,root_folder_id,name,type,shared) values('30000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','test','database',true);
insert into public.access_bindings(id,user_id,root_folder_id,resource_id,consumer,field_mapping) values('40000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000001','test','{"MONGO_URI":"uri"}');
insert into public.secret_access_enrollments(id,user_id,root_folder_id,label,code_hash,binding_ids,status,expires_at) values('50000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','test','fakehash','["40000000-0000-4000-8000-000000000001"]','approved',now()+interval '10 minutes');
do $$ declare r jsonb; v integer; begin
 r:=consume_secret_enrollment('50000000-0000-4000-8000-000000000001','wrong','60000000-0000-4000-8000-000000000001','tokenhash');
 if r->>'status'<>'expired' then raise exception 'wrong code accepted'; end if;
 r:=consume_secret_enrollment('50000000-0000-4000-8000-000000000001','fakehash','60000000-0000-4000-8000-000000000001','tokenhash');
 if r->>'status'<>'approved' then raise exception 'approved poll failed'; end if;
 r:=consume_secret_enrollment('50000000-0000-4000-8000-000000000001','fakehash','60000000-0000-4000-8000-000000000002','tokenhash2');
 if r->>'status'<>'consumed' then raise exception 'poll delivered twice'; end if;
 if (select count(*) from secret_devices)<>1 or (select count(*) from secret_grants)<>1 then raise exception 'device/grant count invalid'; end if;
 r:=reserve_secret_write('70000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','40000000-0000-4000-8000-000000000001',1,'opaque','hmac1',null);
 if r->>'status'<>'pending' then raise exception 'reservation failed'; end if;
 begin
 perform reserve_secret_write('70000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','40000000-0000-4000-8000-000000000001',1,'opaque','different-input',null);
 raise exception 'changed idempotent payload accepted';
 exception when others then if sqlerrm<>'binding_changed' then raise; end if; end;
 begin
 perform reserve_secret_write('70000000-0000-4000-8000-000000000002','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','40000000-0000-4000-8000-000000000001',1,'opaque2','hmac2',null);
 raise exception 'concurrent reservation accepted';
 exception when others then if sqlerrm<>'binding_changed' then raise; end if; end;
 v:=finish_secret_write('70000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001',null);
 if v<>2 then raise exception 'revision not advanced'; end if;
 v:=finish_secret_write('70000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001',null);
 if v<>2 then raise exception 'retry advanced twice'; end if;
 v:=save_root_access_guide('10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001',0,'first');
 if v<>1 then raise exception 'guide failed'; end if;
 v:=save_root_access_guide('10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001',1,'second');
 if v<>2 or (select count(*) from root_access_guide_revisions)<>2 then raise exception 'guide history failed'; end if;
 if has_table_privilege('authenticated','public.access_bindings','SELECT') or has_function_privilege('authenticated','public.consume_secret_enrollment(uuid,text,uuid,text)','EXECUTE') then raise exception 'authenticated raw access granted'; end if;
end $$;
select 'root access SQL acceptance passed' as result;
do $$ declare r jsonb; v integer; expiry timestamptz:=now()+interval '1 day'; begin
 r:=reserve_secret_write('70000000-0000-4000-8000-000000000003','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','40000000-0000-4000-8000-000000000001',2,'opaque3','hmac3',expiry);
 v:=finish_secret_write('70000000-0000-4000-8000-000000000003','10000000-0000-4000-8000-000000000001',null);
 if v<>3 or (select credential_expires_at from access_bindings where id='40000000-0000-4000-8000-000000000001')<>expiry then raise exception 'original expiry lost on recovery'; end if;
 r:=reserve_secret_write('70000000-0000-4000-8000-000000000004','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','40000000-0000-4000-8000-000000000001',3,'opaque4','hmac4',null);
 v:=cancel_secret_write('70000000-0000-4000-8000-000000000004','10000000-0000-4000-8000-000000000001');
 if v<>4 then raise exception 'cancel revision not advanced'; end if;
 begin
 perform finish_secret_write('70000000-0000-4000-8000-000000000004','10000000-0000-4000-8000-000000000001',null);
 raise exception 'late finalize after cancel accepted';
 exception when others then if sqlerrm<>'binding_changed' then raise; end if; end;
 if (select write_operation_id from access_bindings where id='40000000-0000-4000-8000-000000000001') is not null then raise exception 'cancel did not unfreeze binding'; end if;
end $$;
select 'root access recovery SQL acceptance passed' as result;
