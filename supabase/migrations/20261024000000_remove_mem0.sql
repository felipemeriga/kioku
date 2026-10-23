-- Retire Mem0 and permanently delete all rule and episodic records.
-- public.memories is the verified Mem0 pgvector collection (not app documents).
-- Refuse to drop an unexpected similarly named table or dependent app objects.
DO $$
DECLARE
    columns text[];
BEGIN
    IF to_regclass('public.memories') IS NOT NULL THEN
        SELECT array_agg(column_name::text ORDER BY column_name)
          INTO columns
          FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'memories';
        IF columns IS DISTINCT FROM ARRAY['id', 'payload', 'vector']::text[] THEN
            RAISE EXCEPTION 'Refusing to remove unrecognized public.memories table';
        END IF;
        IF EXISTS (
            SELECT 1 FROM public.memories
             WHERE payload->>'folder_id' IS NULL
                OR payload->>'folder_id' IS DISTINCT FROM payload->>'agent_id'
                OR payload->>'scope' NOT IN ('eternal', 'episodic')
                OR payload->>'scope' IS NULL
        ) THEN
            RAISE EXCEPTION 'Refusing to remove records outside the Mem0 folder collection';
        END IF;
        DROP TABLE public.memories;
    END IF;
END $$;

DROP TABLE IF EXISTS public.mem0_sync_configs;
-- The production schema is empty; RESTRICT deliberately protects unknown objects.
DROP SCHEMA IF EXISTS mem0;
