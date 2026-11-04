SELECT tsukai_begin_chat_turn('55555555-5555-5555-5555-555555555555','11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','{"prompt":"hello"}','hello');
SELECT tsukai_begin_chat_turn('55555555-5555-5555-5555-555555555555','11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','{"prompt":"hello"}','hello');
DO $$ BEGIN
  IF (SELECT count(*) FROM messages) <> 1 THEN RAISE EXCEPTION 'duplicate user message'; END IF;
  BEGIN
    PERFORM tsukai_begin_chat_turn('55555555-5555-5555-5555-555555555555','11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','{"prompt":"tampered"}','hello');
    RAISE EXCEPTION 'changed payload accepted';
  EXCEPTION WHEN unique_violation THEN NULL; END;
  BEGIN
    PERFORM tsukai_begin_chat_turn('66666666-6666-6666-6666-666666666666','22222222-2222-2222-2222-222222222222','33333333-3333-3333-3333-333333333333','{}','foreign');
    RAISE EXCEPTION 'foreign owner accepted';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    PERFORM tsukai_begin_chat_turn('66666666-6666-6666-6666-666666666666','11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','{}','concurrent');
    RAISE EXCEPTION 'concurrent turn accepted';
  EXCEPTION WHEN unique_violation THEN NULL; END;
END $$;
UPDATE tsukai_chat_turns SET job_id='job-1',state='submitted';
SELECT tsukai_commit_chat_turn('55555555-5555-5555-5555-555555555555','11111111-1111-1111-1111-111111111111','job-1','answer','{}','[]');
SELECT tsukai_commit_chat_turn('55555555-5555-5555-5555-555555555555','11111111-1111-1111-1111-111111111111','job-1','answer','{}','[]');
DO $$ BEGIN
  IF (SELECT count(*) FROM messages WHERE role='assistant') <> 1 THEN RAISE EXCEPTION 'duplicate assistant'; END IF;
  IF tsukai_register_citation('job-1','attempt-1','source-1','{}') <> 1 THEN RAISE EXCEPTION 'first citation'; END IF;
  IF tsukai_register_citation('job-1','attempt-1','source-1','{}') <> 1 THEN RAISE EXCEPTION 'unstable citation'; END IF;
  IF tsukai_register_citation('job-1','attempt-1','source-2','{}') <> 2 THEN RAISE EXCEPTION 'citation collision'; END IF;
  IF tsukai_register_citation('job-1','attempt-2','source-2','{}') <> 1 THEN RAISE EXCEPTION 'attempt namespace reused'; END IF;
  BEGIN
    PERFORM tsukai_scoped_metadata('22222222-2222-2222-2222-222222222222',ARRAY['44444444-4444-4444-4444-444444444444']::uuid[],'count_files');
    RAISE EXCEPTION 'foreign metadata scope accepted';
  EXCEPTION WHEN raise_exception THEN
    IF SQLERRM <> 'metadata scope revoked' THEN RAISE; END IF;
  END;
END $$;
