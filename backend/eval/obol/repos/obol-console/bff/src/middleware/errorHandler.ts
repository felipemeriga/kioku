/**
 * Terminal error handler. Serializes every failure into the uniform
 * ApiErrorBody envelope (shared/contracts) and includes the request id so the
 * operator can correlate a failed action with server logs and upstream calls.
 */
import type { ErrorRequestHandler, NextFunction, Request, Response } from 'express';
import type { ApiErrorBody } from '@obol/contracts';
import { HttpError } from '../errors.js';

export const errorHandler: ErrorRequestHandler = (
  err: unknown,
  req: Request,
  res: Response,
  _next: NextFunction,
): void => {
  const requestId = req.requestId ?? 'unknown';

  if (err instanceof HttpError) {
    req.logger?.warn('request failed', {
      code: err.code,
      status: err.status,
      upstreamStatus: err.upstreamStatus,
      message: err.message,
    });
    const body: ApiErrorBody = {
      error: {
        code: err.code,
        message: err.message,
        request_id: requestId,
        ...(err.upstreamStatus !== undefined ? { upstream_status: err.upstreamStatus } : {}),
      },
    };
    res.status(err.status).json(body);
    return;
  }

  const message = err instanceof Error ? err.message : 'Internal server error';
  req.logger?.error('unhandled error', { message });
  const body: ApiErrorBody = {
    error: { code: 'internal_error', message: 'Internal server error', request_id: requestId },
  };
  res.status(500).json(body);
};

/** 404 fallback for unmatched API routes. */
export function notFoundHandler(req: Request, res: Response): void {
  const body: ApiErrorBody = {
    error: {
      code: 'not_found',
      message: `No route for ${req.method} ${req.path}`,
      request_id: req.requestId ?? 'unknown',
    },
  };
  res.status(404).json(body);
}
