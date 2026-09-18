/**
 * ledgerClient — typed wrapper around obol-ledger (Python/FastAPI). The console
 * proxies READ money-state here: balances, statements, and payout batches.
 *
 * Ground-truth: the balance display lands on
 * `GET /v1/accounts/{account_id}/balance`.
 *
 * When `mock` is true it serves SPEC fixtures; otherwise it calls the real
 * ledger. Returns console-side contract types (camelCase Money).
 */
import type {
  AccountBalance,
  AccountStatement,
  Dispute,
  PayoutBatch,
  StatementLine,
} from '@obol/contracts';
import { HttpClient, type RequestContext } from './httpClient.js';
import { toMoney, type WireMoney } from './mapping.js';
import { UpstreamError } from '../errors.js';
import {
  DISPUTES,
  PAYOUT_BATCHES,
  SELLER_BALANCES,
  type WireDispute,
  type WirePayoutBatch,
} from './fixtures.js';

interface WireBalance {
  account_id: string;
  available: WireMoney;
  pending: WireMoney;
  as_of: string;
}

interface WireStatementLine {
  entry_id: string;
  posted_at: string;
  memo: string;
  debit: WireMoney | null;
  credit: WireMoney | null;
  running_balance: WireMoney;
}

interface WireStatement {
  account_id: string;
  currency: string;
  opening_balance: WireMoney;
  closing_balance: WireMoney;
  lines: WireStatementLine[];
}

function mapBalance(w: WireBalance): AccountBalance {
  return {
    account_id: w.account_id,
    available: toMoney(w.available),
    pending: toMoney(w.pending),
    as_of: w.as_of,
  };
}

function mapLine(w: WireStatementLine): StatementLine {
  return {
    entry_id: w.entry_id,
    posted_at: w.posted_at,
    memo: w.memo,
    debit: w.debit ? toMoney(w.debit) : null,
    credit: w.credit ? toMoney(w.credit) : null,
    running_balance: toMoney(w.running_balance),
  };
}

function mapPayoutBatch(w: WirePayoutBatch): PayoutBatch {
  return { ...w, amount: toMoney(w.amount) };
}

function mapDispute(w: WireDispute): Dispute {
  return { ...w, amount: toMoney(w.amount) };
}

/** Build the ledger account id for a seller's payable balance (SPEC §Ledger). */
export function sellerPayableAccount(sellerId: string): string {
  return `seller_payable:${sellerId}`;
}

export class LedgerClient {
  constructor(
    private readonly http: HttpClient,
    private readonly mock: boolean,
  ) {}

  /**
   * GROUND-TRUTH BALANCE PATH.
   * GET /v1/accounts/{account_id}/balance — the ledger derives the balance from
   * its immutable journal (SPEC §balances module). The console renders it.
   */
  async getBalance(ctx: RequestContext, accountId: string): Promise<AccountBalance> {
    if (this.mock) {
      const b = SELLER_BALANCES[accountId];
      if (!b) throw new UpstreamError('ledger', 404, `account ${accountId} not found`);
      return mapBalance({
        account_id: accountId,
        available: b.available,
        pending: b.pending,
        as_of: new Date().toISOString(),
      });
    }
    const res = await this.http.request<WireBalance>(
      ctx,
      `v1/accounts/${encodeURIComponent(accountId)}/balance`,
    );
    return mapBalance(res);
  }

  async getStatement(ctx: RequestContext, accountId: string): Promise<AccountStatement> {
    if (this.mock) {
      const b = SELLER_BALANCES[accountId];
      if (!b) throw new UpstreamError('ledger', 404, `account ${accountId} not found`);
      const zero: WireMoney = { amount_minor: 0, currency: b.available.currency };
      const line: WireStatementLine = {
        entry_id: 'jrnl_mock_0001',
        posted_at: '2026-02-11T10:05:12Z',
        memo: 'Settlement chg_0001 seller net',
        debit: null,
        credit: { amount_minor: 11447, currency: 'EUR' },
        running_balance: b.available,
      };
      return {
        account_id: accountId,
        currency: b.available.currency,
        opening_balance: toMoney(zero),
        closing_balance: toMoney(b.available),
        lines: [mapLine(line)],
      };
    }
    const res = await this.http.request<WireStatement>(
      ctx,
      `v1/accounts/${encodeURIComponent(accountId)}/statement`,
    );
    return {
      account_id: res.account_id,
      currency: res.currency,
      opening_balance: toMoney(res.opening_balance),
      closing_balance: toMoney(res.closing_balance),
      lines: res.lines.map(mapLine),
    };
  }

  async listPayoutBatches(
    ctx: RequestContext,
    query: { seller_id?: string } = {},
  ): Promise<PayoutBatch[]> {
    if (this.mock) {
      let rows = PAYOUT_BATCHES;
      if (query.seller_id) rows = rows.filter((p) => p.seller_id === query.seller_id);
      return rows.map(mapPayoutBatch);
    }
    const res = await this.http.request<{ batches: WirePayoutBatch[] }>(ctx, 'v1/payout-batches', { query });
    return res.batches.map(mapPayoutBatch);
  }

  async getPayoutBatch(ctx: RequestContext, batchId: string): Promise<PayoutBatch> {
    if (this.mock) {
      const w = PAYOUT_BATCHES.find((p) => p.id === batchId);
      if (!w) throw new UpstreamError('ledger', 404, `batch ${batchId} not found`);
      return mapPayoutBatch(w);
    }
    const res = await this.http.request<WirePayoutBatch>(
      ctx,
      `v1/payout-batches/${encodeURIComponent(batchId)}`,
    );
    return mapPayoutBatch(res);
  }

  /**
   * Build a payout batch from a seller's payable balance (SPEC §payouts module).
   * The ledger then calls gateway POST /v1/payouts to actually move money.
   */
  async createPayoutBatch(
    ctx: RequestContext,
    input: { seller_id: string; scheduled_for?: string },
  ): Promise<PayoutBatch> {
    if (this.mock) {
      const account = sellerPayableAccount(input.seller_id);
      const b = SELLER_BALANCES[account];
      if (!b) throw new UpstreamError('ledger', 404, `no payable balance for ${input.seller_id}`);
      const batch: WirePayoutBatch = {
        id: `pyt_mock_${Date.now().toString(36)}`,
        seller_id: input.seller_id,
        amount: b.available,
        status: 'scheduled',
        scheduled_for: input.scheduled_for ?? new Date(Date.now() + 86_400_000).toISOString(),
        processor_ref: null,
        created_at: new Date().toISOString(),
      };
      return mapPayoutBatch(batch);
    }
    const res = await this.http.request<WirePayoutBatch>(ctx, 'v1/payout-batches', {
      method: 'POST',
      body: input,
    });
    return mapPayoutBatch(res);
  }

  /**
   * Disputes projection. In production the gateway owns disputes, but the
   * console reads them through the same BFF surface; the ledger exposes the
   * money-impact projection. For the mock we serve fixtures directly.
   */
  async listDisputes(ctx: RequestContext, query: { status?: Dispute['status'] } = {}): Promise<Dispute[]> {
    if (this.mock) {
      let rows = DISPUTES;
      if (query.status) rows = rows.filter((d) => d.status === query.status);
      return rows.map(mapDispute);
    }
    const res = await this.http.request<{ disputes: WireDispute[] }>(ctx, 'v1/disputes', { query });
    return res.disputes.map(mapDispute);
  }
}
