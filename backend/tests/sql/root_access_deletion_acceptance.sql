-- Disposable fixture only: deletion snapshots rotations and cascades both protocols.
insert into access_resources(id,user_id,root_folder_id,name,type,shared) values('30000000-0000-4000-8000-000000000011','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','delete fixture','other',true);
insert into access_bindings(id,user_id,root_folder_id,resource_id,consumer,field_mapping,provider_ref,has_secret) values('40000000-0000-4000-8000-000000000011','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000011','delete fixture','{"TEST_URI":"connection"}','ref-current-v1',true);
insert into access_credentials(id,user_id,root_folder_id,resource_id,label,kind,fields,provider_ref,has_secret) values('80000000-0000-4000-8000-000000000011','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000011','direct','uri','["connection"]','ref-current-v2',true);
insert into credential_write_operations(id,user_id,root_folder_id,credential_id,expected_revision,provider_ref,input_hmac,status) values('90000000-0000-4000-8000-000000000011','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','80000000-0000-4000-8000-000000000011',1,'ref-old-rotation','synthetic-hmac','pending');
do $$ declare refs jsonb; ref text; n integer; begin
 begin
 perform begin_access_resource_deletion('10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000011');
 raise exception 'pending provider write was ignored';
 exception when others then if sqlerrm<>'resource_busy' then raise; end if; end;
 if (select deletion_requested_at from access_resources where name='delete fixture') is not null then raise exception 'busy resource entered deletion'; end if;
 update credential_write_operations set status='complete' where id='90000000-0000-4000-8000-000000000011';
 begin
 perform begin_access_resource_deletion('10000000-0000-4000-8000-000000000099','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000011');
 raise exception 'foreign owner deletion accepted';
 exception when others then if sqlerrm<>'access_denied' then raise; end if; end;
 refs:=begin_access_resource_deletion('10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000011');
 if jsonb_array_length(refs)<>3 or not refs ? 'ref-old-rotation' then raise exception 'deletion lost historic provider objects'; end if;
 if begin_access_resource_deletion('10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000011')<>refs then raise exception 'retry changed snapshot'; end if;
 begin
 perform finish_access_resource_deletion('10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000011');
 raise exception 'metadata forgotten before provider removal';
 exception when others then if sqlerrm<>'resource_busy' then raise; end if; end;
 begin
 perform reserve_credential_write('90000000-0000-4000-8000-000000000012','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','80000000-0000-4000-8000-000000000011',1,'must-not-exist','synthetic',null,null);
 raise exception 'V2 provider write started after deletion';
 exception when others then if sqlerrm<>'resource_deleting' then raise; end if; end;
 begin
 perform reserve_secret_write('70000000-0000-4000-8000-000000000012','10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','40000000-0000-4000-8000-000000000011',1,'must-not-exist-v1','synthetic',null);
 raise exception 'V1 provider write started after deletion';
 exception when others then if sqlerrm<>'resource_deleting' then raise; end if; end;
 for ref in select jsonb_array_elements_text(refs) loop
 n:=ack_access_resource_deletion('10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000011',ref);
 end loop;
 if n<>0 then raise exception 'checkpoint did not drain'; end if;
 perform finish_access_resource_deletion('10000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','30000000-0000-4000-8000-000000000011');
 if exists(select 1 from access_bindings where resource_id='30000000-0000-4000-8000-000000000011') or exists(select 1 from access_credentials where resource_id='30000000-0000-4000-8000-000000000011') or exists(select 1 from credential_write_operations where id='90000000-0000-4000-8000-000000000011') then raise exception 'dependent metadata remained'; end if;
 if not exists(select 1 from access_resources where id='30000000-0000-4000-8000-000000000001') or not exists(select 1 from secret_devices where id='60000000-0000-4000-8000-000000000001') then raise exception 'unrelated data removed'; end if;
 if not exists(select 1 from secret_access_events where action='resource_deleted') then raise exception 'deletion audit missing'; end if;
 if has_function_privilege('authenticated','begin_access_resource_deletion(uuid,uuid,uuid)','EXECUTE') or has_function_privilege('anon','ack_access_resource_deletion(uuid,uuid,uuid,text)','EXECUTE') then raise exception 'provider references exposed'; end if;
end $$;
select 'Resource deletion acceptance passed' as result;
