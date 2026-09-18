/**
 * health/readiness route.
 */
import { Router } from 'express';
import type { Deps } from '../deps.js';

export function healthRouter(deps: Deps): Router {
  const router = Router();

  router.get('/healthz', (_req, res) => {
    res.json({
      status: 'ok',
      service: 'obol-console-bff',
      platform_id: deps.config.platformId,
      ts: new Date().toISOString(),
    });
  });

  return router;
}
