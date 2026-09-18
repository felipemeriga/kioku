/**
 * statements route — read a seller's ledger statement. Proxies to ledger
 * `GET /v1/accounts/{account_id}/statement`.
 */
import { Router } from 'express';
import type { StatementResponse } from '@obol/contracts';
import type { Deps } from '../deps.js';
import { asyncHandler } from '../middleware/asyncHandler.js';
import { badRequest } from '../errors.js';
import { sellerPayableAccount } from '../clients/ledgerClient.js';

export function statementsRouter(deps: Deps): Router {
  const router = Router();

  router.get(
    '/sellers/:sellerId/statement',
    asyncHandler(async (req, res) => {
      const sellerId = req.params.sellerId;
      if (!sellerId) throw badRequest('sellerId is required');
      const accountId = sellerPayableAccount(sellerId);
      const statement = await deps.ledger.getStatement(
        { requestId: req.requestId, logger: req.logger },
        accountId,
      );
      const response: StatementResponse = statement;
      res.json(response);
    }),
  );

  return router;
}
