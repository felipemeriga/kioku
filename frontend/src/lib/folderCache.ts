/**
 * Tiny in-memory stale-while-revalidate cache for folder-scoped data
 * (documents, subfolders, breadcrumbs), keyed by a string.
 *
 * Why: switching folders re-fetches everything over ~150ms-per-call network
 * hops, and the UI blanked to empty while waiting. Seeding from this cache lets
 * a revisited folder render instantly while a background fetch revalidates it.
 *
 * Scope: module-level, so it lives for the session and resets on full reload.
 * No TTL — every read is paired with a background revalidate by the caller, so
 * cached values are only ever a frame stale, never served without a refresh.
 */
const cache = new Map<string, unknown>();

export function getCached<T>(key: string): T | undefined {
  return cache.get(key) as T | undefined;
}

export function setCached<T>(key: string, value: T): void {
  cache.set(key, value);
}

export function clearCached(key: string): void {
  cache.delete(key);
}
