-- Original agent evidence is private, immutable data; no inference providers involved.
CREATE TABLE public.agent_evidence_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
    agent text NOT NULL CHECK (agent IN ('claude_code', 'codex')),
    native_session_id text NOT NULL,
    manifest_path text,
    parent_session_id uuid,
    root_session_id uuid NOT NULL,
    manifest_json jsonb NOT NULL DEFAULT '{"schema":1,"segments":[],"attachments":[],"gaps":[]}',
    manifest_revision bigint NOT NULL DEFAULT 0,
    manifest_sha256 text,
    materialized_revision bigint NOT NULL DEFAULT -1,
    indexed_revision bigint NOT NULL DEFAULT 0,
    index_generation bigint NOT NULL DEFAULT 0,
    parser_version integer NOT NULL DEFAULT 0,
    first_event_at timestamptz,
    last_event_at timestamptz,
    captured_at timestamptz,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    event_count bigint NOT NULL DEFAULT 0,
    capture_status text NOT NULL DEFAULT 'pending',
    index_status text NOT NULL DEFAULT 'pending',
    lifecycle jsonb NOT NULL DEFAULT '{}',
    gaps jsonb NOT NULL DEFAULT '[]',
    producer_gaps jsonb NOT NULL DEFAULT '{}',
    deleted_at timestamptz,
    purged_at timestamptz,
    UNIQUE(user_id, folder_id, agent, native_session_id),
    UNIQUE(id, user_id, folder_id),
    UNIQUE(id, user_id, folder_id, agent),
    FOREIGN KEY(parent_session_id,user_id,folder_id,agent)
        REFERENCES public.agent_evidence_sessions(id,user_id,folder_id,agent)
        DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY(root_session_id,user_id,folder_id,agent)
        REFERENCES public.agent_evidence_sessions(id,user_id,folder_id,agent)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (parent_session_id IS NULL OR parent_session_id <> id)
);
CREATE INDEX agent_evidence_session_activity ON public.agent_evidence_sessions
    (user_id, folder_id, last_event_at DESC, id);
CREATE INDEX agent_evidence_session_parent ON public.agent_evidence_sessions(parent_session_id);

CREATE TABLE public.agent_evidence_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    folder_id uuid NOT NULL,
    session_id uuid NOT NULL,
    batch_id text NOT NULL,
    request_hash text NOT NULL,
    request_json jsonb NOT NULL,
    state text NOT NULL DEFAULT 'staged',
    committed_revision bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    lease_until timestamptz,
    attempts integer NOT NULL DEFAULT 0,
    error_code text,
    cleanup_paths jsonb NOT NULL DEFAULT '[]',
    UNIQUE(user_id, batch_id),
    FOREIGN KEY(session_id, user_id, folder_id)
        REFERENCES public.agent_evidence_sessions(id, user_id, folder_id) ON DELETE CASCADE
);
CREATE INDEX agent_evidence_batch_jobs ON public.agent_evidence_batches(state, updated_at);

CREATE TABLE public.agent_evidence_objects (
    session_id uuid NOT NULL,
    user_id uuid NOT NULL,
    folder_id uuid NOT NULL,
    object_id text NOT NULL,
    descriptor jsonb NOT NULL,
    producer_id text NOT NULL,
    stream_id text NOT NULL,
    generation integer NOT NULL CHECK (generation > 0),
    kind text NOT NULL CHECK (kind IN ('segment', 'attachment')),
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    byte_length bigint NOT NULL CHECK (byte_length > 0 AND byte_length <= 67108864),
    storage_path text,
    uploaded_at timestamptz,
    upload_nonce uuid NOT NULL DEFAULT gen_random_uuid(),
    upload_lease_until timestamptz,
    committed_revision bigint,
    indexed_parser_version integer NOT NULL DEFAULT 0,
    parser_state jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY(session_id, object_id),
    FOREIGN KEY(session_id, user_id, folder_id)
        REFERENCES public.agent_evidence_sessions(id, user_id, folder_id) ON DELETE CASCADE
);
CREATE INDEX agent_evidence_object_order ON public.agent_evidence_objects
    (session_id, stream_id, generation, ((descriptor->>'first_record')::bigint));

CREATE TABLE public.agent_evidence_events (
    session_id uuid NOT NULL,
    user_id uuid NOT NULL,
    folder_id uuid NOT NULL,
    event_id text NOT NULL,
    object_id text NOT NULL,
    stream_id text NOT NULL,
    generation integer NOT NULL,
    record_sequence bigint NOT NULL,
    byte_offset bigint NOT NULL,
    byte_length bigint NOT NULL,
    event_at timestamptz,
    role text NOT NULL,
    event_type text NOT NULL,
    native_id text,
    turn_id text,
    call_id text,
    parent_id text,
    inherited boolean NOT NULL DEFAULT false,
    displayable boolean NOT NULL DEFAULT true,
    content_preview text NOT NULL DEFAULT '',
    content_length bigint NOT NULL DEFAULT 0,
    source_truncated boolean NOT NULL DEFAULT false,
    parser_version integer NOT NULL,
    position text GENERATED ALWAYS AS
        (stream_id || '/' || lpad(generation::text,10,'0') || '/' || lpad(record_sequence::text,20,'0')) STORED,
    PRIMARY KEY(session_id, event_id),
    FOREIGN KEY(session_id, user_id, folder_id)
        REFERENCES public.agent_evidence_sessions(id, user_id, folder_id) ON DELETE CASCADE,
    FOREIGN KEY(session_id, object_id)
        REFERENCES public.agent_evidence_objects(session_id, object_id) ON DELETE CASCADE
);
CREATE INDEX agent_evidence_event_order ON public.agent_evidence_events
    (session_id, stream_id, generation, record_sequence);
CREATE INDEX agent_evidence_event_time ON public.agent_evidence_events(session_id, event_at);
CREATE INDEX agent_evidence_event_position ON public.agent_evidence_events(session_id, position);

CREATE TABLE public.agent_evidence_journal_links (
    user_id uuid NOT NULL,
    folder_id uuid NOT NULL,
    journal_entry_id text NOT NULL,
    journal_date date NOT NULL,
    session_id uuid NOT NULL,
    start_event_id text NOT NULL,
    end_event_id text,
    PRIMARY KEY(user_id, folder_id, journal_entry_id),
    FOREIGN KEY(session_id, user_id, folder_id)
        REFERENCES public.agent_evidence_sessions(id, user_id, folder_id) ON DELETE CASCADE
);

INSERT INTO storage.buckets(id, name, public, file_size_limit)
VALUES ('agent-evidence', 'agent-evidence', false, 67108864)
ON CONFLICT(id) DO UPDATE SET public = false, file_size_limit = 67108864;

-- Every mutation is service-role only and verifies ownership independently of HTTP.
CREATE OR REPLACE FUNCTION public.prepare_agent_evidence(p_user_id uuid, p_request jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_folder uuid := (p_request->>'folder_id')::uuid;
    v_agent text := p_request->>'agent';
    v_native text := p_request->>'native_session_id';
    v_root_native text := COALESCE(p_request->>'native_root_session_id', v_native);
    v_parent_native text := p_request->>'native_parent_session_id';
    v_session public.agent_evidence_sessions%ROWTYPE;
    v_root public.agent_evidence_sessions%ROWTYPE;
    v_parent public.agent_evidence_sessions%ROWTYPE;
    v_batch public.agent_evidence_batches%ROWTYPE;
    v_existing public.agent_evidence_objects%ROWTYPE;
    v_hash text := encode(sha256(convert_to(p_request::text, 'UTF8')), 'hex');
    v_id uuid;
    obj jsonb;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.folders
                   WHERE id=v_folder AND user_id=p_user_id AND kind='repo') THEN
        RAISE EXCEPTION 'evidence_scope_denied' USING ERRCODE='42501';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text || v_folder::text || v_agent, 0));
    SELECT * INTO v_batch FROM public.agent_evidence_batches
        WHERE user_id=p_user_id AND batch_id=p_request->>'batch_id';
    IF FOUND THEN
        IF v_batch.request_hash <> v_hash THEN
            RAISE EXCEPTION 'evidence_batch_conflict' USING ERRCODE='23505';
        END IF;
        RETURN jsonb_build_object('batch_id', v_batch.batch_id, 'session_id', v_batch.session_id);
    END IF;
    IF v_parent_native=v_native OR (v_parent_native IS NULL AND v_root_native<>v_native) THEN
        RAISE EXCEPTION 'evidence_invalid_ancestry' USING ERRCODE='23514';
    END IF;
    SELECT * INTO v_root FROM public.agent_evidence_sessions
      WHERE user_id=p_user_id AND folder_id=v_folder AND agent=v_agent
        AND native_session_id=v_root_native;
    IF NOT FOUND THEN
        v_id := gen_random_uuid();
        INSERT INTO public.agent_evidence_sessions(id,user_id,folder_id,agent,native_session_id,root_session_id)
          VALUES(v_id,p_user_id,v_folder,v_agent,v_root_native,v_id) RETURNING * INTO v_root;
    END IF;
    IF v_root.parent_session_id IS NOT NULL OR v_root.root_session_id<>v_root.id THEN
        RAISE EXCEPTION 'evidence_invalid_ancestry';
    END IF;
    IF v_root.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION 'evidence_deleted' USING ERRCODE='23514';
    END IF;
    IF v_root.manifest_path IS NULL THEN
        UPDATE public.agent_evidence_sessions SET manifest_path=p_user_id::text||'/'||v_folder::text||'/'||v_agent||'/'||v_root_native||'/manifest.json'
          WHERE id=v_root.id RETURNING * INTO v_root;
    END IF;
    IF v_parent_native IS NOT NULL THEN
        SELECT * INTO v_parent FROM public.agent_evidence_sessions
          WHERE user_id=p_user_id AND folder_id=v_folder AND agent=v_agent
            AND native_session_id=v_parent_native AND root_session_id=v_root.id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'evidence_dependency_pending' USING ERRCODE='23514';
        END IF;
        IF v_parent.deleted_at IS NOT NULL THEN
            RAISE EXCEPTION 'evidence_deleted' USING ERRCODE='23514';
        END IF;
    END IF;
    SELECT * INTO v_session FROM public.agent_evidence_sessions
      WHERE user_id=p_user_id AND folder_id=v_folder AND agent=v_agent AND native_session_id=v_native;
    IF NOT FOUND THEN
        INSERT INTO public.agent_evidence_sessions(user_id,folder_id,agent,native_session_id,
            parent_session_id,root_session_id)
        VALUES(p_user_id,v_folder,v_agent,v_native,v_parent.id,v_root.id) RETURNING * INTO v_session;
    END IF;
    IF v_session.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION 'evidence_deleted' USING ERRCODE='23514';
    END IF;
    IF v_session.root_session_id<>v_root.id OR v_session.parent_session_id IS DISTINCT FROM v_parent.id THEN
        RAISE EXCEPTION 'evidence_invalid_ancestry' USING ERRCODE='23514';
    END IF;
    UPDATE public.agent_evidence_sessions SET manifest_path=
      CASE WHEN v_parent.id IS NULL THEN p_user_id::text||'/'||v_folder::text||'/'||v_agent||'/'||v_native
           ELSE left(v_parent.manifest_path,length(v_parent.manifest_path)-14)||'/subagents/'||v_native END
      ||'/manifest.json' WHERE id=v_session.id;
    FOR obj IN SELECT * FROM jsonb_array_elements(p_request->'objects') LOOP
        SELECT * INTO v_existing FROM public.agent_evidence_objects
          WHERE session_id=v_session.id AND object_id=obj->>'id';
        IF FOUND AND (v_existing.descriptor<>obj OR v_existing.producer_id<>p_request->>'producer_id') THEN
            RAISE EXCEPTION 'evidence_object_conflict' USING ERRCODE='23505';
        END IF;
        IF EXISTS (SELECT 1 FROM public.agent_evidence_objects
          WHERE session_id=v_session.id AND stream_id=obj->>'stream_id'
            AND producer_id<>p_request->>'producer_id') THEN
            RAISE EXCEPTION 'evidence_stream_conflict' USING ERRCODE='23505';
        END IF;
        INSERT INTO public.agent_evidence_objects(session_id,user_id,folder_id,object_id,descriptor,
            producer_id,stream_id,generation,kind,sha256,byte_length)
        VALUES(v_session.id,p_user_id,v_folder,obj->>'id',obj,p_request->>'producer_id',
            obj->>'stream_id',(obj->>'generation')::integer,obj->>'kind',obj->>'sha256',
            (obj->>'byte_length')::bigint) ON CONFLICT DO NOTHING;
    END LOOP;
    INSERT INTO public.agent_evidence_batches(user_id,folder_id,session_id,batch_id,request_hash,request_json)
      VALUES(p_user_id,v_folder,v_session.id,p_request->>'batch_id',v_hash,p_request)
      RETURNING * INTO v_batch;
    RETURN jsonb_build_object('batch_id',v_batch.batch_id,'session_id',v_session.id);
END $$;

CREATE OR REPLACE FUNCTION public.commit_agent_evidence(p_user_id uuid, p_batch_id text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    b public.agent_evidence_batches%ROWTYPE;
    s public.agent_evidence_sessions%ROWTYPE;
    o public.agent_evidence_objects%ROWTYPE;
    d jsonb;
    link jsonb;
    v_revision bigint;
    v_manifest jsonb;
    v_validated text[] := '{}';
    v_producer_gaps jsonb;
    v_gaps jsonb;
    v_lifecycle jsonb;
BEGIN
    SELECT * INTO b FROM public.agent_evidence_batches WHERE user_id=p_user_id AND batch_id=p_batch_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'evidence_not_found'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(p_user_id::text || b.folder_id::text ||
        (SELECT agent FROM public.agent_evidence_sessions WHERE id=b.session_id), 0));
    SELECT * INTO b FROM public.agent_evidence_batches WHERE id=b.id FOR UPDATE;
    SELECT * INTO s FROM public.agent_evidence_sessions WHERE id=b.session_id FOR UPDATE;
    IF s.deleted_at IS NOT NULL THEN RAISE EXCEPTION 'evidence_deleted'; END IF;
    IF b.committed_revision IS NOT NULL THEN
        RETURN jsonb_build_object('status','unchanged','session_id',s.id,'revision',b.committed_revision,
            'index_status',s.index_status);
    END IF;
    IF s.manifest_revision<>(b.request_json->>'base_revision')::bigint THEN
        RETURN jsonb_build_object('status','conflict','code','revision_conflict',
            'revision',s.manifest_revision,'session_id',s.id);
    END IF;
    FOR d IN SELECT * FROM jsonb_array_elements(b.request_json->'objects') LOOP
        SELECT * INTO o FROM public.agent_evidence_objects WHERE session_id=s.id AND object_id=d->>'id';
        IF o.uploaded_at IS NULL THEN
            RETURN jsonb_build_object('status','incomplete','code','missing_object','object_id',o.object_id);
        END IF;
        IF o.kind='segment' AND o.committed_revision IS NULL THEN
            IF (d->>'source_start')::bigint=0 THEN
                IF (d->>'first_record')::bigint<>1 THEN RAISE EXCEPTION 'evidence_invalid_range'; END IF;
            ELSIF NOT EXISTS (SELECT 1 FROM public.agent_evidence_objects prior
                WHERE prior.session_id=s.id AND prior.stream_id=o.stream_id AND prior.generation=o.generation
                AND prior.kind='segment' AND (prior.committed_revision IS NOT NULL
                    OR prior.object_id=ANY(v_validated))
                AND (prior.descriptor->>'source_end')::bigint=(d->>'source_start')::bigint
                AND (prior.descriptor->>'last_record')::bigint=(d->>'first_record')::bigint-1) THEN
                RETURN jsonb_build_object('status','dependency_pending','code','dependency_pending');
            END IF;
            IF EXISTS (SELECT 1 FROM public.agent_evidence_objects prior
              WHERE prior.session_id=s.id AND prior.object_id<>o.object_id AND prior.kind='segment'
                AND prior.stream_id=o.stream_id AND prior.generation=o.generation
                AND (prior.committed_revision IS NOT NULL OR prior.object_id=ANY(v_validated))
                AND int8range((prior.descriptor->>'source_start')::bigint,
                              (prior.descriptor->>'source_end')::bigint,'[)') &&
                    int8range((d->>'source_start')::bigint,(d->>'source_end')::bigint,'[)')) THEN
                RAISE EXCEPTION 'evidence_range_conflict';
            END IF;
            v_validated := array_append(v_validated,o.object_id);
        END IF;
    END LOOP;
    v_revision := s.manifest_revision+1;
    UPDATE public.agent_evidence_objects SET committed_revision=COALESCE(committed_revision,v_revision)
      WHERE session_id=s.id AND object_id IN (SELECT value->>'id' FROM jsonb_array_elements(b.request_json->'objects'));
    FOR link IN SELECT * FROM jsonb_array_elements(COALESCE(b.request_json->'journal_links','[]')) LOOP
        -- Association is supplemental. Conflicting/late aliases cannot reject raw evidence.
        INSERT INTO public.agent_evidence_journal_links
          VALUES(p_user_id,s.folder_id,link->>'journal_entry_id',(link->>'journal_date')::date,
                 s.id,link->>'start_event_id',link->>'end_event_id')
        ON CONFLICT (user_id,folder_id,journal_entry_id) DO UPDATE
        SET end_event_id=EXCLUDED.end_event_id
        WHERE agent_evidence_journal_links.session_id=EXCLUDED.session_id
          AND agent_evidence_journal_links.start_event_id=EXCLUDED.start_event_id
          AND EXCLUDED.end_event_id IS NOT NULL
          AND (agent_evidence_journal_links.end_event_id IS NULL
            OR NOT EXISTS(SELECT 1 FROM public.agent_evidence_events old_end
              WHERE old_end.session_id=s.id AND old_end.event_id=agent_evidence_journal_links.end_event_id)
            OR EXISTS(SELECT 1 FROM public.agent_evidence_events new_end
              JOIN public.agent_evidence_events old_end ON old_end.session_id=new_end.session_id
              WHERE new_end.session_id=s.id AND new_end.event_id=EXCLUDED.end_event_id
                AND old_end.event_id=agent_evidence_journal_links.end_event_id
                AND new_end.position>=old_end.position));
    END LOOP;
    v_producer_gaps := jsonb_set(s.producer_gaps,ARRAY[b.request_json->>'producer_id'],
        COALESCE(b.request_json->'gaps','[]'),true);
    SELECT COALESCE(jsonb_agg(DISTINCT gap),'[]') INTO v_gaps
      FROM jsonb_each(v_producer_gaps) producer, jsonb_array_elements(producer.value) gap;
    v_lifecycle := s.lifecycle || COALESCE(b.request_json->'lifecycle','{}');
    SELECT jsonb_build_object('schema',1,'revision',v_revision,'agent',s.agent,
        'native_session_id',s.native_session_id,'parent_session_id',s.parent_session_id,
        'gaps',v_gaps,'lifecycle',v_lifecycle,
        'children',COALESCE((SELECT jsonb_agg(jsonb_build_object('id',child.id,
            'native_session_id',child.native_session_id) ORDER BY child.id)
            FROM public.agent_evidence_sessions child WHERE child.parent_session_id=s.id
            AND child.deleted_at IS NULL),'[]'),
        'segments',COALESCE(jsonb_agg(descriptor || jsonb_build_object('storage_path',storage_path)
            ORDER BY stream_id,generation,
            (descriptor->>'source_start')::bigint) FILTER(WHERE kind='segment'),'[]'),
        'attachments',COALESCE(jsonb_agg(descriptor || jsonb_build_object('storage_path',storage_path)
            ORDER BY object_id)
            FILTER(WHERE kind='attachment'),'[]')) INTO v_manifest
      FROM public.agent_evidence_objects WHERE session_id=s.id AND committed_revision IS NOT NULL;
    UPDATE public.agent_evidence_sessions SET manifest_json=v_manifest,
        manifest_sha256=encode(sha256(convert_to(v_manifest::text,'UTF8')),'hex'),manifest_revision=v_revision,
        index_status=CASE WHEN EXISTS(SELECT 1 FROM public.agent_evidence_objects
          WHERE session_id=s.id AND kind='segment' AND committed_revision IS NOT NULL
            AND indexed_parser_version<1) THEN 'pending' ELSE 'ready' END,
        indexed_revision=CASE WHEN EXISTS(SELECT 1 FROM public.agent_evidence_objects
          WHERE session_id=s.id AND kind='segment' AND committed_revision IS NOT NULL
            AND indexed_parser_version<1) THEN indexed_revision ELSE v_revision END,
        capture_status='captured',captured_at=now(),ingested_at=now(),
        lifecycle=v_lifecycle,producer_gaps=v_producer_gaps,gaps=v_gaps WHERE id=s.id;
    IF s.parent_session_id IS NOT NULL THEN
      UPDATE public.agent_evidence_sessions parent SET
        manifest_json=jsonb_set(jsonb_set(parent.manifest_json,'{children}',
          COALESCE((SELECT jsonb_agg(jsonb_build_object('id',child.id,'native_session_id',child.native_session_id)
            ORDER BY child.id) FROM public.agent_evidence_sessions child
            WHERE child.parent_session_id=parent.id AND child.deleted_at IS NULL),'[]')),
          '{revision}',to_jsonb(parent.manifest_revision+1)),
        manifest_revision=parent.manifest_revision+1,manifest_sha256=NULL
      WHERE parent.id=s.parent_session_id;
      UPDATE public.agent_evidence_sessions SET
        manifest_sha256=encode(sha256(convert_to(manifest_json::text,'UTF8')),'hex')
        WHERE id=s.parent_session_id;
    END IF;
    UPDATE public.agent_evidence_batches SET committed_revision=v_revision,state='pending',updated_at=now()
      WHERE id=b.id;
    RETURN jsonb_build_object('status','accepted','session_id',s.id,'revision',v_revision,'index_status',
        (SELECT index_status FROM public.agent_evidence_sessions WHERE id=s.id));
END $$;

CREATE OR REPLACE FUNCTION public.claim_agent_evidence_upload(p_user_id uuid,p_session_id uuid,p_object_id text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE s public.agent_evidence_sessions%ROWTYPE; o public.agent_evidence_objects%ROWTYPE;
BEGIN
    SELECT * INTO s FROM public.agent_evidence_sessions WHERE id=p_session_id AND user_id=p_user_id FOR UPDATE;
    IF NOT FOUND OR s.deleted_at IS NOT NULL THEN RAISE EXCEPTION 'evidence_deleted'; END IF;
    SELECT * INTO o FROM public.agent_evidence_objects WHERE session_id=s.id AND object_id=p_object_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'evidence_not_found'; END IF;
    UPDATE public.agent_evidence_objects SET upload_lease_until=now()+interval '3 minutes',
        storage_path=COALESCE(storage_path,left(s.manifest_path,length(s.manifest_path)-14)||
          CASE WHEN o.kind='segment' THEN '/segments/' ELSE '/attachments/' END||o.object_id||'-'||o.upload_nonce::text||
          CASE WHEN o.kind='segment' THEN '.jsonl' ELSE '' END)
        WHERE session_id=s.id AND object_id=p_object_id;
    RETURN jsonb_build_object('nonce',o.upload_nonce,'uploaded',o.uploaded_at IS NOT NULL);
END $$;

CREATE OR REPLACE FUNCTION public.finish_agent_evidence_upload(
    p_user_id uuid,p_session_id uuid,p_object_id text,p_nonce uuid,p_path text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
    PERFORM 1 FROM public.agent_evidence_sessions WHERE id=p_session_id AND user_id=p_user_id
        AND deleted_at IS NULL FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'evidence_deleted'; END IF;
    UPDATE public.agent_evidence_objects SET storage_path=p_path,uploaded_at=now(),upload_lease_until=NULL
      WHERE session_id=p_session_id AND user_id=p_user_id AND object_id=p_object_id AND upload_nonce=p_nonce;
    IF NOT FOUND THEN RAISE EXCEPTION 'evidence_upload_expired'; END IF;
END $$;

CREATE OR REPLACE FUNCTION public.expire_agent_evidence_batch(p_batch_row_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE b public.agent_evidence_batches%ROWTYPE; o public.agent_evidence_objects%ROWTYPE;
    paths jsonb := '[]';
BEGIN
    SELECT * INTO b FROM public.agent_evidence_batches WHERE id=p_batch_row_id;
    IF NOT FOUND THEN RETURN paths; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(b.user_id::text || b.folder_id::text ||
        (SELECT agent FROM public.agent_evidence_sessions WHERE id=b.session_id),0));
    SELECT * INTO b FROM public.agent_evidence_batches WHERE id=b.id FOR UPDATE;
    IF b.committed_revision IS NOT NULL OR b.created_at>now()-interval '7 days' THEN RETURN paths; END IF;
    paths:=b.cleanup_paths;
    FOR o IN SELECT * FROM public.agent_evidence_objects obj WHERE obj.session_id=b.session_id
        AND obj.committed_revision IS NULL AND (obj.upload_lease_until IS NULL OR obj.upload_lease_until<now())
        AND NOT EXISTS(SELECT 1 FROM public.agent_evidence_batches fresh WHERE fresh.session_id=obj.session_id
            AND fresh.created_at>now()-interval '7 days' AND fresh.state='staged'
            AND fresh.request_json->'objects' @> jsonb_build_array(jsonb_build_object('id',obj.object_id)))
        FOR UPDATE LOOP
        IF o.storage_path IS NOT NULL THEN paths:=paths || to_jsonb(o.storage_path); END IF;
        -- A new upload receives a new physical key. An expired cleanup can never
        -- delete bytes belonging to a subsequent acknowledged upload.
        UPDATE public.agent_evidence_objects SET uploaded_at=NULL,storage_path=NULL,
            upload_nonce=gen_random_uuid(),upload_lease_until=NULL WHERE session_id=o.session_id AND object_id=o.object_id;
    END LOOP;
    UPDATE public.agent_evidence_batches SET state='expired',cleanup_paths=paths WHERE id=b.id;
    RETURN paths;
END $$;

CREATE OR REPLACE FUNCTION public.publish_agent_evidence_index(
    p_session_id uuid, p_object_id text, p_events jsonb, p_state jsonb, p_parser_version integer,
    p_complete boolean DEFAULT true)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE s public.agent_evidence_sessions%ROWTYPE; e jsonb;
BEGIN
    SELECT * INTO s FROM public.agent_evidence_sessions WHERE id=p_session_id FOR UPDATE;
    IF NOT FOUND OR s.deleted_at IS NOT NULL THEN RETURN; END IF;
    IF NOT EXISTS(SELECT 1 FROM public.agent_evidence_objects WHERE session_id=s.id
      AND object_id=p_object_id AND committed_revision IS NOT NULL) THEN
        RAISE EXCEPTION 'evidence_not_committed';
    END IF;
    FOR e IN SELECT * FROM jsonb_array_elements(p_events) LOOP
      INSERT INTO public.agent_evidence_events(session_id,user_id,folder_id,event_id,object_id,
          stream_id,generation,record_sequence,byte_offset,byte_length,event_at,role,event_type,
          native_id,turn_id,call_id,parent_id,inherited,displayable,content_preview,content_length,source_truncated,parser_version)
      VALUES(s.id,s.user_id,s.folder_id,e->>'event_id',p_object_id,e->>'stream_id',
          (e->>'generation')::integer,(e->>'record_sequence')::bigint,(e->>'byte_offset')::bigint,
          (e->>'byte_length')::bigint,(e->>'event_at')::timestamptz,e->>'role',e->>'event_type',
          e->>'native_id',e->>'turn_id',e->>'call_id',e->>'parent_id',
          COALESCE((e->>'inherited')::boolean,false),COALESCE((e->>'displayable')::boolean,true),
          e->>'content_preview',COALESCE((e->>'content_length')::bigint,0),
          COALESCE((e->>'source_truncated')::boolean,false),p_parser_version)
      ON CONFLICT(session_id,event_id) DO UPDATE SET
          content_preview=excluded.content_preview,role=excluded.role,event_type=excluded.event_type,
          displayable=excluded.displayable,inherited=excluded.inherited,
          source_truncated=excluded.source_truncated,content_length=excluded.content_length,
          parser_version=excluded.parser_version
      WHERE agent_evidence_events.parser_version<=excluded.parser_version;
    END LOOP;
    -- Only established native call identities establish duplicate tool-result representations.
    -- Prefer the richer retained result; all alternatives stay available through raw-records.
    UPDATE public.agent_evidence_events e SET displayable=false
      WHERE e.session_id=s.id AND e.event_type='tool_result' AND e.call_id IS NOT NULL
      AND EXISTS(SELECT 1 FROM public.agent_evidence_events richer WHERE richer.session_id=e.session_id
        AND richer.stream_id=e.stream_id AND richer.generation=e.generation
        AND richer.event_type=e.event_type AND richer.call_id=e.call_id
        AND richer.turn_id IS NOT DISTINCT FROM e.turn_id AND richer.displayable
        AND (richer.content_length>e.content_length OR (richer.content_length=e.content_length
          AND richer.record_sequence<e.record_sequence)));
    UPDATE public.agent_evidence_sessions SET index_generation=index_generation+1 WHERE id=s.id;
    IF NOT p_complete THEN RETURN; END IF;
    UPDATE public.agent_evidence_objects SET indexed_parser_version=p_parser_version,parser_state=p_state
      WHERE session_id=s.id AND object_id=p_object_id AND indexed_parser_version<=p_parser_version;
    UPDATE public.agent_evidence_sessions SET
      event_count=(SELECT count(*) FROM public.agent_evidence_events WHERE session_id=s.id AND displayable AND NOT inherited),
      first_event_at=(SELECT min(event_at) FROM public.agent_evidence_events WHERE session_id=s.id AND displayable AND NOT inherited),
      last_event_at=(SELECT max(event_at) FROM public.agent_evidence_events WHERE session_id=s.id AND displayable AND NOT inherited),
      parser_version=GREATEST(parser_version,p_parser_version),
      indexed_revision=CASE WHEN NOT EXISTS(SELECT 1 FROM public.agent_evidence_objects
        WHERE session_id=s.id AND kind='segment' AND committed_revision IS NOT NULL
          AND indexed_parser_version<p_parser_version) THEN manifest_revision ELSE indexed_revision END,
      index_status=CASE WHEN NOT EXISTS(SELECT 1 FROM public.agent_evidence_objects
        WHERE session_id=s.id AND kind='segment' AND committed_revision IS NOT NULL
          AND indexed_parser_version<p_parser_version) THEN 'ready' ELSE 'pending' END WHERE id=s.id;
END $$;

CREATE OR REPLACE FUNCTION public.agent_evidence_days(
    p_user_id uuid,p_folder_id uuid,p_session_id uuid,p_timezone text,p_from date,p_to date)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=public AS $$
    SELECT COALESCE(jsonb_agg(day ORDER BY day->>'date'),'[]') FROM (
      SELECT jsonb_build_object('date',(e.event_at AT TIME ZONE p_timezone)::date,
          'event_count',count(*),'turn_count',count(DISTINCT e.turn_id),
          'first_event_id',(array_agg(e.event_id ORDER BY e.position))[1]) AS day
      FROM public.agent_evidence_events e JOIN public.agent_evidence_sessions s ON s.id=e.session_id
      WHERE e.user_id=p_user_id AND e.folder_id=p_folder_id AND e.session_id=p_session_id
        AND s.deleted_at IS NULL AND e.displayable AND NOT e.inherited
        AND (e.event_at AT TIME ZONE p_timezone)::date BETWEEN p_from AND p_to
      GROUP BY (e.event_at AT TIME ZONE p_timezone)::date
    ) days;
$$;

CREATE OR REPLACE FUNCTION public.delete_agent_evidence(p_user_id uuid,p_folder_id uuid,p_session_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE count_deleted integer;
BEGIN
    IF NOT EXISTS(SELECT 1 FROM public.agent_evidence_sessions
      WHERE id=p_session_id AND user_id=p_user_id AND folder_id=p_folder_id) THEN
        RAISE EXCEPTION 'evidence_not_found';
    END IF;
    WITH RECURSIVE tree AS (
      SELECT id FROM public.agent_evidence_sessions WHERE id=p_session_id
      UNION ALL SELECT child.id FROM public.agent_evidence_sessions child JOIN tree ON child.parent_session_id=tree.id
    ) UPDATE public.agent_evidence_sessions SET deleted_at=COALESCE(deleted_at,now()),
      capture_status='deleted',index_status='deleted' WHERE id IN(SELECT id FROM tree)
      AND user_id=p_user_id AND folder_id=p_folder_id;
    GET DIAGNOSTICS count_deleted = ROW_COUNT;
    RETURN jsonb_build_object('status','deleted','sessions',count_deleted);
END $$;

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['agent_evidence_sessions','agent_evidence_batches','agent_evidence_objects',
      'agent_evidence_events','agent_evidence_journal_links'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
    EXECUTE format('CREATE POLICY owner_read ON public.%I FOR SELECT TO authenticated USING (user_id=auth.uid())',t);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon,authenticated',t);
    EXECUTE format('GRANT SELECT ON public.%I TO authenticated',t);
    EXECUTE format('GRANT ALL ON public.%I TO service_role',t);
  END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.prepare_agent_evidence(uuid,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.commit_agent_evidence(uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.publish_agent_evidence_index(uuid,text,jsonb,jsonb,integer,boolean) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.delete_agent_evidence(uuid,uuid,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.agent_evidence_days(uuid,uuid,uuid,text,date,date) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_agent_evidence_upload(uuid,uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.finish_agent_evidence_upload(uuid,uuid,text,uuid,text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.expire_agent_evidence_batch(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.prepare_agent_evidence(uuid,jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.commit_agent_evidence(uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.publish_agent_evidence_index(uuid,text,jsonb,jsonb,integer,boolean) TO service_role;
GRANT EXECUTE ON FUNCTION public.delete_agent_evidence(uuid,uuid,uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.agent_evidence_days(uuid,uuid,uuid,text,date,date) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_agent_evidence_upload(uuid,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.finish_agent_evidence_upload(uuid,uuid,text,uuid,text) TO service_role;
GRANT EXECUTE ON FUNCTION public.expire_agent_evidence_batch(uuid) TO service_role;

-- Independent of owner/folder foreign keys: deletion must survive their cascade.
CREATE TABLE public.agent_evidence_purge_outbox (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    storage_paths jsonb NOT NULL,
    not_before timestamptz NOT NULL DEFAULT now()+interval '15 minutes',
    created_at timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL DEFAULT 0
);
ALTER TABLE public.agent_evidence_purge_outbox ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.agent_evidence_purge_outbox FROM anon,authenticated;
GRANT ALL ON public.agent_evidence_purge_outbox TO service_role;
CREATE OR REPLACE FUNCTION public.archive_agent_evidence_purge_paths()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE paths jsonb; prefix text; node public.agent_evidence_sessions%ROWTYPE;
BEGIN
    SELECT COALESCE(jsonb_agg(storage_path),'[]') INTO paths
      FROM public.agent_evidence_objects WHERE session_id=OLD.id AND storage_path IS NOT NULL;
    prefix:=OLD.native_session_id; node:=OLD;
    WHILE node.parent_session_id IS NOT NULL LOOP
        SELECT * INTO node FROM public.agent_evidence_sessions WHERE id=node.parent_session_id;
        EXIT WHEN NOT FOUND;
        prefix:=node.native_session_id||'/subagents/'||prefix;
    END LOOP;
    prefix:=OLD.user_id::text||'/'||OLD.folder_id::text||'/'||OLD.agent||'/'||prefix;
    paths:=paths||jsonb_build_array(COALESCE(OLD.manifest_path,prefix||'/manifest.json'));
    INSERT INTO public.agent_evidence_purge_outbox(storage_paths) VALUES(paths);
    RETURN OLD;
END $$;
CREATE TRIGGER agent_evidence_purge_before_delete BEFORE DELETE ON public.agent_evidence_sessions
    FOR EACH ROW EXECUTE FUNCTION public.archive_agent_evidence_purge_paths();
REVOKE ALL ON FUNCTION public.archive_agent_evidence_purge_paths() FROM PUBLIC;
CREATE OR REPLACE FUNCTION public.archive_agent_evidence_object_purge_path()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
BEGIN
    IF OLD.storage_path IS NOT NULL THEN
        INSERT INTO public.agent_evidence_purge_outbox(storage_paths)
          VALUES(jsonb_build_array(OLD.storage_path));
    END IF;
    RETURN OLD;
END $$;
CREATE TRIGGER agent_evidence_object_purge_before_delete BEFORE DELETE ON public.agent_evidence_objects
    FOR EACH ROW EXECUTE FUNCTION public.archive_agent_evidence_object_purge_path();
REVOKE ALL ON FUNCTION public.archive_agent_evidence_object_purge_path() FROM PUBLIC;
