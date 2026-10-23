const REFRESH_TIMEOUT_MS = 30 * 60 * 1000;

/** Job completion is independent of changes to the generated content. */
export function refreshState(
  startedAt: string | null | undefined,
  finishedAt: string | null | undefined,
  error: string | null | undefined,
  now: number
): "idle" | "running" | "completed" | "failed" | "timed-out" {
  if (!startedAt) return "idle";
  const started = new Date(startedAt).getTime();
  if (finishedAt && new Date(finishedAt).getTime() >= started)
    return error ? "failed" : "completed";
  if (!Number.isFinite(started) || now - started > REFRESH_TIMEOUT_MS)
    return "timed-out";
  return "running";
}
