/**
 * Mounts every API router under a single Express Router. Everything here is
 * served under the `/api` prefix by the app (see app.ts).
 */
import { Router } from 'express';
import type { Deps } from '../deps.js';
import { healthRouter } from './health.js';
import { refundsRouter } from './refunds.js';
import { chargesRouter } from './charges.js';
import { balancesRouter } from './balances.js';
import { statementsRouter } from './statements.js';
import { payoutsRouter } from './payouts.js';
import { disputesRouter } from './disputes.js';
import { sellersRouter } from './sellers.js';

export function apiRouter(deps: Deps): Router {
  const router = Router();
  router.use(healthRouter(deps));
  router.use(sellersRouter(deps));
  router.use(chargesRouter(deps));
  router.use(refundsRouter(deps)); // POST /charges/:id/refunds → gateway
  router.use(balancesRouter(deps)); // GET /sellers/:id/balance → ledger
  router.use(statementsRouter(deps));
  router.use(payoutsRouter(deps));
  router.use(disputesRouter(deps));
  return router;
}
