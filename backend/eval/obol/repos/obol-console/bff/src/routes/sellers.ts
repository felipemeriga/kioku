/**
 * sellers route — the platform's roster of sub-merchants. Used to populate
 * seller pickers on the Balance and Payouts screens. Served from fixtures /
 * gateway seller directory.
 */
import { Router } from 'express';
import type { Seller } from '@obol/contracts';
import type { Deps } from '../deps.js';
import { asyncHandler } from '../middleware/asyncHandler.js';
import { SELLERS } from '../clients/fixtures.js';

export function sellersRouter(_deps: Deps): Router {
  const router = Router();

  router.get(
    '/sellers',
    asyncHandler(async (_req, res) => {
      const sellers: Seller[] = Object.values(SELLERS);
      res.json({ sellers });
    }),
  );

  return router;
}
