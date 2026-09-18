/**
 * balances route — the GROUND-TRUTH balance path on the console side.
 *
 *   web BalancePage → useBalances → GET /api/sellers/:sellerId/balance  (this)
 *     → ledgerClient.getBalance → ledger GET /v1/accounts/{account_id}/balance
 *
 * The console asks by seller; the BFF resolves the ledger account id
 * (`seller_payable:{seller_id}`, SPEC §Ledger model) before calling the ledger.
 */
import { Router } from 'express';
import type { BalanceResponse } from '@obol/contracts';
import type { Deps } from '../deps.js';
import { asyncHandler } from '../middleware/asyncHandler.js';
import { badRequest } from '../errors.js';
import { sellerPayableAccount } from '../clients/ledgerClient.js';

export function balancesRouter(deps: Deps): Router {
  const router = Router();

  router.get(
    '/sellers/:sellerId/balance',
    asyncHandler(async (req, res) => {
      const sellerId = req.params.sellerId;
      if (!sellerId) throw badRequest('sellerId is required');

      const accountId = sellerPayableAccount(sellerId);
      const balance = await deps.ledger.getBalance(
        { requestId: req.requestId, logger: req.logger },
        accountId,
      );

      const response: BalanceResponse = { balance, seller_id: sellerId };
      res.json(response);
    }),
  );

  // Direct account lookup, for operators who know the raw ledger account id.
  router.get(
    '/accounts/:accountId/balance',
    asyncHandler(async (req, res) => {
      const accountId = req.params.accountId;
      if (!accountId) throw badRequest('accountId is required');
      const balance = await deps.ledger.getBalance(
        { requestId: req.requestId, logger: req.logger },
        accountId,
      );
      res.json(balance);
    }),
  );

  return router;
}
