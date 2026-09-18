/**
 * Verifies the GROUND-TRUTH balance path through the BFF:
 *   GET /api/sellers/:id/balance → resolve seller_payable:{id}
 *     → ledgerClient.getBalance (mock mode).
 */
import { describe, it, expect } from 'vitest';
import request from 'supertest';
import { loadConfig } from '../config.js';
import { createApp } from '../app.js';
import { buildMockDeps } from '../deps.js';
import type { BalanceResponse, ApiErrorBody } from '@obol/contracts';

function app() {
  const config = loadConfig({ NODE_ENV: 'test', GATEWAY_BASE_URL: 'mock', LEDGER_BASE_URL: 'mock' } as NodeJS.ProcessEnv);
  return createApp(config, { deps: buildMockDeps(config) });
}

describe('GET /api/sellers/:sellerId/balance', () => {
  it('resolves the seller payable account and returns its balance', async () => {
    const res = await request(app()).get('/api/sellers/sell_atelier/balance').expect(200);
    const body = res.body as BalanceResponse;
    expect(body.seller_id).toBe('sell_atelier');
    expect(body.balance.account_id).toBe('seller_payable:sell_atelier');
    expect(body.balance.available.currency).toBe('EUR');
    expect(Number.isInteger(body.balance.available.amountMinor)).toBe(true);
  });

  it('returns 404 for an unknown seller account', async () => {
    const res = await request(app()).get('/api/sellers/sell_ghost/balance').expect(404);
    const body = res.body as ApiErrorBody;
    expect(body.error.code).toBe('not_found');
  });

  it('serves a health check', async () => {
    const res = await request(app()).get('/api/healthz').expect(200);
    expect(res.body.status).toBe('ok');
    expect(res.body.platform_id).toBe('plat_marisqueira');
  });
});
