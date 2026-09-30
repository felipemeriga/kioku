-- Persist the agent's debug trace (reasoning, tool calls, retrieved chunks with
-- rerank scores) alongside the assistant message, so the chat UI's Inspect card
-- survives reloads and is available on past answers — not just the live turn.
-- Nullable: only set when the turn ran with debug mode on.
ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS debug jsonb;
