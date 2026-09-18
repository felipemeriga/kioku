/**
 * Attaches a correlation id to every request. Honors an inbound `x-request-id`
 * (e.g. from a reverse proxy) or mints one. The id is echoed on the response
 * and propagated to upstream gateway/ledger calls so a single operator action
 * can be traced across all three services.
 */
import { randomUUID } from 'node:crypto';
import type { NextFunction, Request, Response } from 'express';
import { createLogger, type Logger } from '../logger.js';

declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      requestId: string;
      logger: Logger;
    }
  }
}

export function requestId(logLevel: string) {
  return (req: Request, res: Response, next: NextFunction): void => {
    const inbound = req.header('x-request-id');
    const id = inbound && inbound.trim() !== '' ? inbound : `req_${randomUUID()}`;
    req.requestId = id;
    req.logger = createLogger(logLevel, { requestId: id, method: req.method, path: req.path });
    res.setHeader('x-request-id', id);
    next();
  };
}
