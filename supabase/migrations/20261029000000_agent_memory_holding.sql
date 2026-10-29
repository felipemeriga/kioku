-- Immutable source evidence and durable processing queue for Manabi events.
-- No model output is written here. Only the service role may call the accept RPC.
CREATE TABLE public.memory_raw_events (
    user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    event_id text NOT NULL CHECK (event_id ~ '^[a-f0-9]{64}$'),
    folder_id uuid NOT NULL REFERENCES public.folders(id) ON DELETE CASCADE,
    machine_id uuid NOT NULL,
    source text NOT NULL CHECK (source = 'claude_code'),
    source_schema_version integer NOT NULL CHECK (source_schema_version = 1),
    session_id text NOT NULL CHECK (length(session_id) BETWEEN 1 AND 160),
    record_position bigint NOT NULL CHECK (record_position >= 0),
    content_hash text NOT NULL CHECK (content_hash ~ '^[a-f0-9]{64}$'),
    raw_ciphertext text NOT NULL,
    wrapped_dek text NOT NULL,
    nonce text NOT NULL,
    redacted_content text NOT NULL,
    event_time timestamptz,
    observed_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    provenance text NOT NULL CHECK (provenance IN ('user', 'assistant', 'tool_result', 'external_text', 'unknown')),
    sensitivity text NOT NULL CHECK (sensitivity IN ('normal', 'redacted')),
    PRIMARY KEY (user_id, event_id),
    FOREIGN KEY (user_id, machine_id) REFERENCES public.remote_machines(user_id, id) ON DELETE CASCADE
);
CREATE INDEX memory_raw_events_scope_time_idx
    ON public.memory_raw_events(user_id, folder_id, event_time DESC);

CREATE TABLE public.memory_holding (
    user_id uuid NOT NULL,
    event_id text NOT NULL,
    state text NOT NULL DEFAULT 'QUEUED' CHECK (state IN ('QUEUED', 'LEASED', 'DONE', 'PENDING_REVIEW', 'DEAD_LETTER')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    lease_owner text,
    lease_until timestamptz,
    next_attempt_at timestamptz,
    last_error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, event_id),
    FOREIGN KEY (user_id, event_id) REFERENCES public.memory_raw_events(user_id, event_id) ON DELETE CASCADE
);
CREATE INDEX memory_holding_poll_idx
    ON public.memory_holding(state, next_attempt_at, lease_until, created_at);

ALTER TABLE public.memory_raw_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.memory_holding ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.memory_raw_events, public.memory_holding FROM anon, authenticated;
GRANT ALL ON public.memory_raw_events, public.memory_holding TO service_role;

CREATE FUNCTION public.accept_memory_event(
    p_user_id uuid,
    p_machine_id uuid,
    p_event_id text,
    p_folder_id uuid,
    p_source text,
    p_source_schema_version integer,
    p_session_id text,
    p_record_position bigint,
    p_content_hash text,
    p_raw_ciphertext text,
    p_wrapped_dek text,
    p_nonce text,
    p_redacted_content text,
    p_event_time timestamptz,
    p_observed_at timestamptz,
    p_provenance text,
    p_sensitivity text
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_existing_hash text;
    v_inserted_count bigint := 0;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.remote_machines m
        WHERE m.user_id = p_user_id AND m.id = p_machine_id
          AND EXISTS (
              SELECT 1 FROM jsonb_array_elements(coalesce(m.inventory, '[]'::jsonb)) AS repo(value)
              WHERE repo.value->>'folder_id' = p_folder_id::text
          )
    ) OR NOT EXISTS (
        SELECT 1 FROM public.folders f
        WHERE f.user_id = p_user_id AND f.id = p_folder_id AND f.kind = 'repo'
    ) THEN
        RAISE EXCEPTION 'memory_scope_denied' USING ERRCODE = 'P0001';
    END IF;

    INSERT INTO public.memory_raw_events (
        user_id, event_id, folder_id, machine_id, source, source_schema_version, session_id,
        record_position, content_hash, raw_ciphertext, wrapped_dek, nonce,
        redacted_content, event_time, observed_at, provenance, sensitivity
    ) VALUES (
        p_user_id, p_event_id, p_folder_id, p_machine_id, p_source, p_source_schema_version, p_session_id,
        p_record_position, p_content_hash, p_raw_ciphertext, p_wrapped_dek, p_nonce,
        p_redacted_content, p_event_time, p_observed_at, p_provenance, p_sensitivity
    ) ON CONFLICT (user_id, event_id) DO NOTHING;
    GET DIAGNOSTICS v_inserted_count = ROW_COUNT;

    IF v_inserted_count = 0 THEN
        SELECT content_hash INTO v_existing_hash FROM public.memory_raw_events
        WHERE user_id = p_user_id AND event_id = p_event_id;
        IF v_existing_hash IS DISTINCT FROM p_content_hash THEN
            RAISE EXCEPTION 'memory_hash_conflict' USING ERRCODE = 'P0001';
        END IF;
        RETURN 'duplicate';
    END IF;

    INSERT INTO public.memory_holding(user_id, event_id)
    VALUES (p_user_id, p_event_id);
    RETURN 'stored';
END;
$$;
REVOKE ALL ON FUNCTION public.accept_memory_event(
    uuid, uuid, text, uuid, text, integer, text, bigint, text, text, text, text,
    text, timestamptz, timestamptz, text, text
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.accept_memory_event(
    uuid, uuid, text, uuid, text, integer, text, bigint, text, text, text, text,
    text, timestamptz, timestamptz, text, text
) TO service_role;
