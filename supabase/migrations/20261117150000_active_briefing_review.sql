-- Active-only planners no longer read retired detailed documentation. Keep CAS
-- for legacy plans that explicitly captured a document revision, and for edits.
DO $patch$
DECLARE definition text;
BEGIN
 definition:=pg_get_functiondef('public.apply_maintenance_result(uuid,uuid,text,jsonb)'::regprocedure);
 IF position('IF prep.operation IN (''documentation'',''review_plan'') THEN' IN definition)=0 THEN
  RAISE EXCEPTION 'Unexpected maintenance publication contract';
 END IF;
 definition:=replace(definition,
 'IF prep.operation IN (''documentation'',''review_plan'') THEN',
 'IF prep.operation=''documentation'' OR (prep.operation=''review_plan'' AND prep.snapshot ? ''documentation_revision'') THEN');
 EXECUTE definition;
END
$patch$;
