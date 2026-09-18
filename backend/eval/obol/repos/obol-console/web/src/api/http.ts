/**
 * Low-level fetch helper for the SPA → BFF. Everything the console web app does
 * goes through here; it never calls gateway or ledger directly.
 */
import type { ApiErrorBody } from '@obol/contracts';

const BASE_URL = (import.meta.env.VITE_BFF_BASE_URL as string | undefined) ?? '/api';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { accept: 'application/json', ...opts.headers };
  if (opts.body !== undefined) headers['content-type'] = 'application/json';

  const res = await fetch(`${BASE_URL}${path}`, {
    method: opts.method ?? 'GET',
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal ?? null,
  });

  const text = await res.text();
  const data = text ? JSON.parse(text) : undefined;

  if (!res.ok) {
    const err = data as ApiErrorBody | undefined;
    throw new ApiError(
      res.status,
      err?.error.code ?? 'unknown',
      err?.error.message ?? `Request failed with ${res.status}`,
      err?.error.request_id,
    );
  }
  return data as T;
}
