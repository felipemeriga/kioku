/**
 * A thin, typed fetch wrapper shared by the gateway and ledger clients. Handles
 * timeouts, auth headers, request-id propagation, JSON (de)serialization, and
 * uniform error translation into UpstreamError / UpstreamTimeoutError.
 */
import { UpstreamError, UpstreamTimeoutError } from '../errors.js';
import type { Logger } from '../logger.js';
import type { UpstreamConfig } from '../config.js';

export type Upstream = 'gateway' | 'ledger';

export interface RequestContext {
  /** Correlation id, propagated to the upstream as `x-request-id`. */
  requestId: string;
  logger: Logger;
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  /** Parsed JSON body to send. */
  body?: unknown;
  /** Extra headers (e.g. Idempotency-Key on refund/charge creation). */
  headers?: Record<string, string>;
  /** Query string params. Undefined values are dropped. */
  query?: Record<string, string | number | undefined>;
}

export class HttpClient {
  constructor(
    private readonly upstream: Upstream,
    private readonly config: UpstreamConfig,
    private readonly timeoutMs: number,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  private url(path: string, query?: RequestOptions['query']): string {
    const u = new URL(path, this.config.baseUrl.endsWith('/') ? this.config.baseUrl : `${this.config.baseUrl}/`);
    if (query) {
      for (const [k, v] of Object.entries(query)) {
        if (v !== undefined) u.searchParams.set(k, String(v));
      }
    }
    return u.toString();
  }

  async request<T>(ctx: RequestContext, path: string, opts: RequestOptions = {}): Promise<T> {
    const method = opts.method ?? 'GET';
    const url = this.url(path, opts.query);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    const headers: Record<string, string> = {
      accept: 'application/json',
      authorization: `Bearer ${this.config.apiKey}`,
      'x-request-id': ctx.requestId,
      ...opts.headers,
    };
    if (opts.body !== undefined) headers['content-type'] = 'application/json';

    const started = Date.now();
    ctx.logger.debug('upstream request', { upstream: this.upstream, method, path });

    let res: Response;
    try {
      res = await this.fetchImpl(url, {
        method,
        headers,
        body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
        signal: controller.signal,
      });
    } catch (err) {
      clearTimeout(timer);
      if (err instanceof Error && err.name === 'AbortError') {
        ctx.logger.warn('upstream timeout', { upstream: this.upstream, path, timeoutMs: this.timeoutMs });
        throw new UpstreamTimeoutError(this.upstream, this.timeoutMs);
      }
      const message = err instanceof Error ? err.message : String(err);
      ctx.logger.error('upstream network error', { upstream: this.upstream, path, message });
      throw new UpstreamError(this.upstream, 0, `${this.upstream} unreachable: ${message}`);
    } finally {
      clearTimeout(timer);
    }

    const durationMs = Date.now() - started;
    const text = await res.text();
    const parsed = text ? safeJson(text) : undefined;

    if (!res.ok) {
      const message = extractMessage(parsed) ?? `${this.upstream} responded ${res.status}`;
      ctx.logger.warn('upstream non-2xx', {
        upstream: this.upstream,
        path,
        status: res.status,
        durationMs,
      });
      throw new UpstreamError(this.upstream, res.status, message);
    }

    ctx.logger.info('upstream ok', { upstream: this.upstream, method, path, status: res.status, durationMs });
    return parsed as T;
  }
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

function extractMessage(parsed: unknown): string | undefined {
  if (parsed && typeof parsed === 'object') {
    const obj = parsed as Record<string, unknown>;
    if (typeof obj.message === 'string') return obj.message;
    if (obj.error && typeof obj.error === 'object') {
      const inner = obj.error as Record<string, unknown>;
      if (typeof inner.message === 'string') return inner.message;
    }
    if (typeof obj.detail === 'string') return obj.detail;
  }
  return undefined;
}
