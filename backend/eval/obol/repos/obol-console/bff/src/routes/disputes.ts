/**
 * disputes route — list buyer chargebacks (SPEC §Dispute). Proxied through the
 * ledger's money-impact projection.
 */
import { Router } from 'express';
import type { Dispute, ListDisputesResponse } from '@obol/contracts';
import type { Deps } from '../deps.js';
import { asyncHandler } from '../middleware/asyncHandler.js';
import { badRequest } from '../errors.js';

const VALID_STATUS: Dispute['status'][] = ['open', 'won', 'lost'];

export function disputesRouter(deps: Deps): Router {
  const router = Router();

  router.get(
    '/disputes',
    asyncHandler(async (req, res) => {
      const status = req.query.status as string | undefined;
      if (status && !VALID_STATUS.includes(status as Dispute['status'])) {
        throw badRequest(`status must be one of: ${VALID_STATUS.join(', ')}`);
      }
      const disputes = await deps.ledger.listDisputes(
        { requestId: req.requestId, logger: req.logger },
        status ? { status: status as Dispute['status'] } : {},
      );
      const response: ListDisputesResponse = { disputes };
      res.json(response);
    }),
  );

  return router;
}
