-- Empty tool output is valid evidence; JSONL segments must remain nonempty.
ALTER TABLE public.agent_evidence_objects
    DROP CONSTRAINT agent_evidence_objects_byte_length_check;
ALTER TABLE public.agent_evidence_objects
    ADD CONSTRAINT agent_evidence_objects_byte_length_check
    CHECK (byte_length >= 0 AND byte_length <= 67108864
        AND (kind = 'attachment' OR byte_length > 0));
