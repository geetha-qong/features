/**
 * Simple in-memory cache for expensive API calls that don't change often.
 * Keyed by URL-like strings; each entry has a timestamp for staleness checks.
 */

interface CacheEntry<T> {
  data: T;
  ts: number;
}

const _cache = new Map<string, CacheEntry<unknown>>();

export const STALE_MS = {
  sheets:     5 * 60 * 1000,
  detections: 2 * 60 * 1000,
  entities:   2 * 60 * 1000,
  graph:     10 * 60 * 1000,
};

export function cachedFetch<T>(
  key: string,
  fetcher: () => Promise<T>,
  staleMs: number,
): Promise<T> {
  const cached = _cache.get(key) as CacheEntry<T> | undefined;
  if (cached && Date.now() - cached.ts < staleMs) {
    return Promise.resolve(cached.data);
  }
  return fetcher().then((data) => {
    _cache.set(key, { data, ts: Date.now() });
    return data;
  });
}

/** Invalidate all cache entries for a specific job (call after reprocess). */
export function invalidateJob(jobId: number): void {
  for (const key of Array.from(_cache.keys())) {
    if (key.includes(`/jobs/${jobId}/`)) {
      _cache.delete(key);
    }
  }
}
