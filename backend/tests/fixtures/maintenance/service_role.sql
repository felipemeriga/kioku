-- Match production service-role access inside this isolated minimal schema.
-- Do not change global role attributes or grant anything to the runner role.
GRANT USAGE ON SCHEMA public,auth TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public,auth TO service_role;
DO $$ DECLARE target record; BEGIN
    FOR target IN SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relrowsecurity LOOP
        EXECUTE format('CREATE POLICY fixture_service ON public.%I TO service_role USING(true) WITH CHECK(true)',target.relname);
    END LOOP;
END $$;
