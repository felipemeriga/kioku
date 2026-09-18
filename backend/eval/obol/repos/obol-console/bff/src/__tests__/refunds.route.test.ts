/**
 * Verifies the GROUND-TRUTH refund path through the BFF:
 *   POST /api/charges/:id/refunds → gatewayClient.createRefund (mock mode).
 */
import { describe, it, expect } from 'vitest';
import request from 'supertest';
import { loadConfig } from '../config.js';
import { createApp } from '../app.js';
import { buildMockDeps } from '../deps.js';
import type { CreateRefundResponse, ApiErrorBody } from '@obol/contracts';

function app() {
  const config = loadConfig({ NODE_ENV: 'test', GATEWAY_BASE_URL: 'mock', LEDGER_BASE_URL: 'mock' } as NodeJS.ProcessEnv);
  return createApp(config, { deps: buildMockDeps(config) });
}

describe('POST /api/charges/:chargeId/refunds', () => {
  it('issues a full refund for chg_0001 and reports charge_status=refunded', async () => {
    const res = await request(app())
      .post('/api/charges/chg_0001/refunds')
      .send({ reason: 'requested_by_customer' })
      .expect(201);

    const body = res.body as CreateRefundResponse;
    expect(body.refund.charge_id).toBe('chg_0001');
    expect(body.refund.status).toBe('completed');
    expect(body.refund.amount).toEqual({ amountMinor: 12000, currency: 'EUR' });
    expect(body.charge_status).toBe('refunded');
    expect(res.headers['x-request-id']).toBeTruthy();
  });

  it('issues a partial refund and reports partially_refunded', async () => {
    const res = await request(app())
      .post('/api/charges/chg_0001/refunds')
      .send({ reason: 'duplicate', amount: { amountMinor: 3000, currency: 'EUR' } })
      .expect(201);

    const body = res.body as CreateRefundResponse;
    expect(body.refund.amount).toEqual({ amountMinor: 3000, currency: 'EUR' });
    expect(body.charge_status).toBe('partially_refunded');
  });

  it('rejects an invalid reason with 400', async () => {
    const res = await request(app())
      .post('/api/charges/chg_0001/refunds')
      .send({ reason: 'nope' })
      .expect(400);
    const body = res.body as ApiErrorBody;
    expect(body.error.code).toBe('bad_request');
    expect(body.error.request_id).toBeTruthy();
  });

  it('returns 404 when the charge does not exist', async () => {
    const res = await request(app())
      .post('/api/charges/chg_missing/refunds')
      .send({ reason: 'other' })
      .expect(404);
    const body = res.body as ApiErrorBody;
    expect(body.error.code).toBe('not_found');
  });
});
