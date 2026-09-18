/**
 * BFF error taxonomy. Everything that leaves the BFF as a non-2xx is one of
 * these, so the error-handler middleware can serialize a uniform envelope.
 */
export class HttpError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly upstreamStatus?: number,
  ) {
    super(message);
    this.name = 'HttpError';
  }
}

export const badRequest = (msg: string): HttpError => new HttpError(400, 'bad_request', msg);
export const notFound = (msg = 'Resource not found'): HttpError =>
  new HttpError(404, 'not_found', msg);

/**
 * Raised by the upstream clients when gateway/ledger returns a non-2xx or the
 * request times out. Carries the upstream status so the operator can see it.
 */
export class UpstreamError extends HttpError {
  constructor(
    public readonly upstream: 'gateway' | 'ledger',
    upstreamStatus: number,
    message: string,
  ) {
    // Map upstream 4xx through as-is where sensible; otherwise surface 502.
    const status = upstreamStatus === 404 ? 404 : upstreamStatus >= 400 && upstreamStatus < 500 ? upstreamStatus : 502;
    super(status, upstreamStatus === 404 ? 'not_found' : 'upstream_error', message, upstreamStatus);
    this.name = 'UpstreamError';
  }
}

export class UpstreamTimeoutError extends HttpError {
  constructor(public readonly upstream: 'gateway' | 'ledger', timeoutMs: number) {
    super(504, 'upstream_timeout', `${upstream} did not respond within ${timeoutMs}ms`);
    this.name = 'UpstreamTimeoutError';
  }
}
