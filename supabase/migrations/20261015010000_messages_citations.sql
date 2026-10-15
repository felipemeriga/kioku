-- Persist the turn's inline-citation registry alongside the assistant message:
-- an ordered list mapping each [N] the model emitted to its source (document or
-- code file:line, with a url/excerpt the UI needs to open it). Set whenever the
-- turn retrieved and cited sources, so citations survive reloads and render on
-- past answers — not just the live SSE stream. Nullable.
ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS citations jsonb;
