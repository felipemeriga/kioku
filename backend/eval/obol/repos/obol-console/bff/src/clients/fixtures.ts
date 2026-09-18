/**
 * Deterministic fixture data mirroring SPEC §"Fixed sample data". The upstream
 * clients fall back to these when GATEWAY_BASE_URL / LEDGER_BASE_URL point at
 * the built-in mock (i.e. when the real gateway/ledger aren't running), so the
 * console is demoable stand-alone. All ids, amounts and fees match the spec so
 * examples line up across repos and docs.
 *
 *   Platform: plat_marisqueira — "Marisqueira Marketplace", PT, 290 bps.
 *   Sellers:  sell_atelier ("Atelier Costa"), sell_ceramica ("Cerâmica do Vale").
 *   Charge:   chg_0001 — €120.00, platform_fee €3.48, processor_fee €2.05,
 *             seller net €114.47.
 */
import type {
  Charge,
  Dispute,
  PayoutBatch,
  Refund,
  Seller,
} from '@obol/contracts';
import type { WireMoney } from './mapping.js';

const eur = (amount_minor: number): WireMoney => ({ amount_minor, currency: 'EUR' });

export const PLATFORM_ID = 'plat_marisqueira';

export const SELLERS: Record<string, Seller> = {
  sell_atelier: {
    id: 'sell_atelier',
    platform_id: PLATFORM_ID,
    display_name: 'Atelier Costa',
    kyc_status: 'verified',
    payout_currency: 'EUR',
    created_at: '2026-01-04T09:12:00Z',
  },
  sell_ceramica: {
    id: 'sell_ceramica',
    platform_id: PLATFORM_ID,
    display_name: 'Cerâmica do Vale',
    kyc_status: 'verified',
    payout_currency: 'EUR',
    created_at: '2026-01-06T14:41:00Z',
  },
};

/**
 * Wire-shaped charges (snake_case Money) exactly as the gateway would return
 * them. chg_0001 is the canonical spec example.
 */
export interface WireCharge extends Omit<Charge, 'amount' | 'platform_fee' | 'processor_fee'> {
  amount: WireMoney;
  platform_fee: WireMoney;
  processor_fee: WireMoney;
}

export const CHARGES: WireCharge[] = [
  {
    id: 'chg_0001',
    platform_id: PLATFORM_ID,
    seller_id: 'sell_atelier',
    amount: eur(12000),
    platform_fee: eur(348),
    processor_fee: eur(205),
    status: 'settled',
    idempotency_key: 'ik_chg_0001',
    processor_ref: 'ch_mock_3f9a1',
    created_at: '2026-02-11T10:05:12Z',
  },
  {
    id: 'chg_0002',
    platform_id: PLATFORM_ID,
    seller_id: 'sell_ceramica',
    amount: eur(4500),
    platform_fee: eur(131),
    processor_fee: eur(96),
    status: 'settled',
    idempotency_key: 'ik_chg_0002',
    processor_ref: 'ch_mock_7b2c4',
    created_at: '2026-02-12T16:22:40Z',
  },
  {
    id: 'chg_0003',
    platform_id: PLATFORM_ID,
    seller_id: 'sell_atelier',
    amount: eur(8900),
    platform_fee: eur(258),
    processor_fee: eur(163),
    status: 'partially_refunded',
    idempotency_key: 'ik_chg_0003',
    processor_ref: 'ch_mock_9d1e8',
    created_at: '2026-02-13T08:47:03Z',
  },
  {
    id: 'chg_0004',
    platform_id: PLATFORM_ID,
    seller_id: 'sell_ceramica',
    amount: eur(21000),
    platform_fee: eur(609),
    processor_fee: eur(335),
    status: 'authorized',
    idempotency_key: 'ik_chg_0004',
    processor_ref: 'ch_mock_1a6f0',
    created_at: '2026-02-14T11:59:55Z',
  },
];

export interface WireRefund extends Omit<Refund, 'amount'> {
  amount: WireMoney;
}

export const REFUNDS: WireRefund[] = [
  {
    id: 'rfnd_0001',
    charge_id: 'chg_0003',
    amount: eur(3000),
    reason: 'requested_by_customer',
    status: 'completed',
    created_at: '2026-02-13T18:30:11Z',
  },
];

export interface WirePayoutBatch extends Omit<PayoutBatch, 'amount'> {
  amount: WireMoney;
}

export const PAYOUT_BATCHES: WirePayoutBatch[] = [
  {
    id: 'pyt_0001',
    seller_id: 'sell_atelier',
    amount: eur(11447),
    status: 'paid',
    scheduled_for: '2026-02-15T00:00:00Z',
    processor_ref: 'po_mock_5c8b2',
    created_at: '2026-02-14T22:00:00Z',
  },
  {
    id: 'pyt_0002',
    seller_id: 'sell_ceramica',
    amount: eur(4273),
    status: 'scheduled',
    scheduled_for: '2026-02-18T00:00:00Z',
    processor_ref: null,
    created_at: '2026-02-15T22:00:00Z',
  },
];

export interface WireDispute extends Omit<Dispute, 'amount'> {
  amount: WireMoney;
}

export const DISPUTES: WireDispute[] = [
  {
    id: 'dsp_0001',
    charge_id: 'chg_0002',
    amount: eur(4500),
    status: 'open',
    created_at: '2026-02-16T09:03:22Z',
  },
];

/**
 * seller_payable balances derived from the settlement postings. For
 * sell_atelier the settled chg_0001 net is €114.47 (12000 − 348 − 205), but
 * pyt_0001 already paid that out, so the *available* payable is what remains
 * from later activity. We keep these fixed for demo determinism.
 */
export const SELLER_BALANCES: Record<string, { available: WireMoney; pending: WireMoney }> = {
  'seller_payable:sell_atelier': { available: eur(5900), pending: eur(0) },
  'seller_payable:sell_ceramica': { available: eur(4273), pending: eur(21000 - 609 - 335) },
};
