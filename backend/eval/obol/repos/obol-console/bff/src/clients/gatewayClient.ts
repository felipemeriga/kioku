/**
 * gatewayClient — typed wrapper around obol-gateway (Go). The console proxies
 * WRITE money-movement (refunds) here, plus charge reads.
 *
 * Ground-truth: the refund action lands on `POST /v1/charges/{id}/refunds`.
 *
 * When `mock` is true (GATEWAY_BASE_URL points at the built-in mock) it serves
 * SPEC fixtures so the console runs stand-alone. Otherwise it calls the real
 * gateway via HttpClient. Either way it returns console-side contract types
 * (camelCase Money).
 */
import type { Charge, Refund, RefundReason } from '@obol/contracts';
import { HttpClient, type RequestContext } from './httpClient.js';
import { toMoney, fromMoney, type WireMoney } from './mapping.js';
import { UpstreamError } from '../errors.js';
import {
  CHARGES,
  REFUNDS,
  type WireCharge,
  type WireRefund,
} from './fixtures.js';

interface WireChargeDetail {
  charge: WireCharge;
  refunds: WireRefund[];
}

interface WireRefundResult {
  refund: WireRefund;
  charge_status: Charge['status'];
}

function mapCharge(w: WireCharge): Charge {
  return {
    ...w,
    amount: toMoney(w.amount),
    platform_fee: toMoney(w.platform_fee),
    processor_fee: toMoney(w.processor_fee),
  };
}

function mapRefund(w: WireRefund): Refund {
  return { ...w, amount: toMoney(w.amount) };
}

export interface CreateRefundInput {
  chargeId: string;
  amount?: WireMoney;
  reason: RefundReason;
  /** Idempotency-Key header value (SPEC: gateway requires it on writes). */
  idempotencyKey: string;
}

export class GatewayClient {
  constructor(
    private readonly http: HttpClient,
    private readonly mock: boolean,
  ) {}

  async listCharges(
    ctx: RequestContext,
    query: { seller_id?: string; status?: Charge['status']; limit?: number; cursor?: string } = {},
  ): Promise<{ charges: Charge[]; next_cursor: string | null }> {
    if (this.mock) {
      let rows = CHARGES;
      if (query.seller_id) rows = rows.filter((c) => c.seller_id === query.seller_id);
      if (query.status) rows = rows.filter((c) => c.status === query.status);
      return { charges: rows.map(mapCharge), next_cursor: null };
    }
    const res = await this.http.request<{ charges: WireCharge[]; next_cursor: string | null }>(
      ctx,
      'v1/charges',
      { query },
    );
    return { charges: res.charges.map(mapCharge), next_cursor: res.next_cursor };
  }

  async getCharge(ctx: RequestContext, chargeId: string): Promise<{ charge: Charge; refunds: Refund[] }> {
    if (this.mock) {
      const w = CHARGES.find((c) => c.id === chargeId);
      if (!w) throw new UpstreamError('gateway', 404, `charge ${chargeId} not found`);
      const refunds = REFUNDS.filter((r) => r.charge_id === chargeId);
      return { charge: mapCharge(w), refunds: refunds.map(mapRefund) };
    }
    const res = await this.http.request<WireChargeDetail>(ctx, `v1/charges/${encodeURIComponent(chargeId)}`);
    return { charge: mapCharge(res.charge), refunds: res.refunds.map(mapRefund) };
  }

  /**
   * GROUND-TRUTH REFUND PATH.
   * POST /v1/charges/{id}/refunds — the gateway performs the processor refund
   * and emits `refund.completed`, which the ledger consumes to post the
   * reversal entry. The console never does the accounting itself.
   */
  async createRefund(
    ctx: RequestContext,
    input: CreateRefundInput,
  ): Promise<{ refund: Refund; charge_status: Charge['status'] }> {
    if (this.mock) {
      const charge = CHARGES.find((c) => c.id === input.chargeId);
      if (!charge) throw new UpstreamError('gateway', 404, `charge ${input.chargeId} not found`);
      const amount: WireMoney = input.amount ?? charge.amount;
      const full = amount.amount_minor >= charge.amount.amount_minor;
      const refund: WireRefund = {
        id: `rfnd_mock_${Date.now().toString(36)}`,
        charge_id: input.chargeId,
        amount,
        reason: input.reason,
        status: 'completed',
        created_at: new Date().toISOString(),
      };
      return {
        refund: mapRefund(refund),
        charge_status: full ? 'refunded' : 'partially_refunded',
      };
    }

    // Send wire-shaped Money to the gateway.
    const wireBody: { reason: RefundReason; amount?: WireMoney } = { reason: input.reason };
    if (input.amount) wireBody.amount = input.amount;

    const res = await this.http.request<WireRefundResult>(
      ctx,
      `v1/charges/${encodeURIComponent(input.chargeId)}/refunds`,
      {
        method: 'POST',
        body: wireBody,
        headers: { 'Idempotency-Key': input.idempotencyKey },
      },
    );
    return { refund: mapRefund(res.refund), charge_status: res.charge_status };
  }

  /** Execute a seller payout via the gateway processor (SPEC: POST /v1/payouts). */
  async executePayout(
    ctx: RequestContext,
    input: { seller_id: string; amount: WireMoney; batch_id: string; idempotencyKey: string },
  ): Promise<{ processor_ref: string }> {
    if (this.mock) {
      return { processor_ref: `po_mock_${Date.now().toString(36)}` };
    }
    return this.http.request<{ processor_ref: string }>(ctx, 'v1/payouts', {
      method: 'POST',
      body: { seller_id: input.seller_id, amount: input.amount, batch_id: input.batch_id },
      headers: { 'Idempotency-Key': input.idempotencyKey },
    });
  }
}

/** Re-export for callers that need to hand raw wire Money to createRefund. */
export { fromMoney };
