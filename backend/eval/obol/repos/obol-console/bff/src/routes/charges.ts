/**
 * charges route — read transactions and charge detail. Proxies to gateway
 * (which owns charges/refunds). Used by the Transactions screen.
 */
import { Router } from 'express';
import type {
  Charge,
  ChargeDetailResponse,
  ListChargesResponse,
} from '@obol/contracts';
import type { Deps } from '../deps.js';
import { asyncHandler } from '../middleware/asyncHandler.js';
import { badRequest } from '../errors.js';

const VALID_STATUS: Charge['status'][] = [
  'pending',
  'authorized',
  'settled',
  'failed',
  'refunded',
  'partially_refunded',
];

export function chargesRouter(deps: Deps): Router {
  const router = Router();

  router.get(
    '/charges',
    asyncHandler(async (req, res) => {
      const status = req.query.status as string | undefined;
      if (status && !VALID_STATUS.includes(status as Charge['status'])) {
        throw badRequest(`status must be one of: ${VALID_STATUS.join(', ')}`);
      }
      const limitRaw = req.query.limit as string | undefined;
      const limit = limitRaw ? Number.parseInt(limitRaw, 10) : undefined;
      if (limit !== undefined && (Number.isNaN(limit) || limit <= 0)) {
        throw badRequest('limit must be a positive integer');
      }

      const result = await deps.gateway.listCharges(
        { requestId: req.requestId, logger: req.logger },
        {
          ...(req.query.seller_id ? { seller_id: String(req.query.seller_id) } : {}),
          ...(status ? { status: status as Charge['status'] } : {}),
          ...(limit ? { limit } : {}),
          ...(req.query.cursor ? { cursor: String(req.query.cursor) } : {}),
        },
      );
      const response: ListChargesResponse = result;
      res.json(response);
    }),
  );

  router.get(
    '/charges/:chargeId',
    asyncHandler(async (req, res) => {
      const chargeId = req.params.chargeId;
      if (!chargeId) throw badRequest('chargeId is required');
      const result = await deps.gateway.getCharge(
        { requestId: req.requestId, logger: req.logger },
        chargeId,
      );
      const response: ChargeDetailResponse = result;
      res.json(response);
    }),
  );

  return router;
}
