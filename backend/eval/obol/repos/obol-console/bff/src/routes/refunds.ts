/**
 * refunds route — the GROUND-TRUTH refund path on the console side.
 *
 *   web RefundButton → useRefund → POST /api/charges/:chargeId/refunds  (this)
 *     → gatewayClient.createRefund → gateway POST /v1/charges/{id}/refunds
 *       → processor.refund → emit refund.completed → ledger posts reversal.
 *
 * The BFF mints an Idempotency-Key so a double-click can't double-refund (SPEC:
 * gateway requires Idempotency-Key on writes).
 */
import { Router } from 'express';
import { randomUUID } from 'node:crypto';
import type { CreateRefundRequest, CreateRefundResponse, RefundReason } from '@obol/contracts';
import type { Deps } from '../deps.js';
import { asyncHandler } from '../middleware/asyncHandler.js';
import { badRequest } from '../errors.js';
import { fromMoney } from '../clients/gatewayClient.js';

const VALID_REASONS: RefundReason[] = [
  'requested_by_customer',
  'duplicate',
  'fraudulent',
  'product_not_received',
  'other',
];

export function refundsRouter(deps: Deps): Router {
  const router = Router();

  router.post(
    '/charges/:chargeId/refunds',
    asyncHandler(async (req, res) => {
      const chargeId = req.params.chargeId;
      if (!chargeId) throw badRequest('chargeId is required');

      const body = req.body as Partial<CreateRefundRequest>;
      if (!body || typeof body !== 'object') throw badRequest('request body is required');
      if (!body.reason || !VALID_REASONS.includes(body.reason)) {
        throw badRequest(`reason must be one of: ${VALID_REASONS.join(', ')}`);
      }
      if (body.amount !== undefined) {
        if (
          typeof body.amount.amountMinor !== 'number' ||
          !Number.isInteger(body.amount.amountMinor) ||
          body.amount.amountMinor <= 0 ||
          typeof body.amount.currency !== 'string'
        ) {
          throw badRequest('amount must be { amountMinor: positive integer, currency: string }');
        }
      }

      // Prefer a client-supplied idempotency key (safe retries); else mint one.
      const idempotencyKey = req.header('idempotency-key') ?? `ik_${randomUUID()}`;

      const result = await deps.gateway.createRefund(
        { requestId: req.requestId, logger: req.logger },
        {
          chargeId,
          reason: body.reason,
          ...(body.amount ? { amount: fromMoney(body.amount) } : {}),
          idempotencyKey,
        },
      );

      const response: CreateRefundResponse = {
        refund: result.refund,
        charge_status: result.charge_status,
      };
      res.status(201).json(response);
    }),
  );

  return router;
}
