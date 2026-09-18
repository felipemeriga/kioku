/**
 * payouts route — list/inspect payout batches and schedule a new one. Proxies
 * to ledger payout-batches (SPEC §payouts module: ledger builds a batch from a
 * seller's payable balance, then calls gateway POST /v1/payouts to move money).
 */
import { Router } from 'express';
import type {
  CreatePayoutBatchRequest,
  CreatePayoutBatchResponse,
  ListPayoutsResponse,
} from '@obol/contracts';
import type { Deps } from '../deps.js';
import { asyncHandler } from '../middleware/asyncHandler.js';
import { badRequest } from '../errors.js';

export function payoutsRouter(deps: Deps): Router {
  const router = Router();

  router.get(
    '/payouts',
    asyncHandler(async (req, res) => {
      const batches = await deps.ledger.listPayoutBatches(
        { requestId: req.requestId, logger: req.logger },
        req.query.seller_id ? { seller_id: String(req.query.seller_id) } : {},
      );
      const response: ListPayoutsResponse = { batches };
      res.json(response);
    }),
  );

  router.get(
    '/payouts/:batchId',
    asyncHandler(async (req, res) => {
      const batchId = req.params.batchId;
      if (!batchId) throw badRequest('batchId is required');
      const batch = await deps.ledger.getPayoutBatch(
        { requestId: req.requestId, logger: req.logger },
        batchId,
      );
      res.json(batch);
    }),
  );

  router.post(
    '/payouts',
    asyncHandler(async (req, res) => {
      const body = req.body as Partial<CreatePayoutBatchRequest>;
      if (!body?.seller_id || typeof body.seller_id !== 'string') {
        throw badRequest('seller_id is required');
      }
      const batch = await deps.ledger.createPayoutBatch(
        { requestId: req.requestId, logger: req.logger },
        {
          seller_id: body.seller_id,
          ...(body.scheduled_for ? { scheduled_for: body.scheduled_for } : {}),
        },
      );
      const response: CreatePayoutBatchResponse = { batch };
      res.status(201).json(response);
    }),
  );

  return router;
}
