/**
 * Front-end sample data mirroring SPEC §"Fixed sample data" (camelCase Money,
 * as the SPA sees it after the BFF has mapped from the wire). Used by component
 * tests and for local Storybook-style rendering. Keeps chg_0001 = €120.00 etc.
 */
import type { Charge, Dispute, PayoutBatch, Seller } from '@obol/contracts';
import { money } from '@obol/contracts';

export const sampleSellers: Seller[] = [
  {
    id: 'sell_atelier',
    platform_id: 'plat_marisqueira',
    display_name: 'Atelier Costa',
    kyc_status: 'verified',
    payout_currency: 'EUR',
    created_at: '2026-01-04T09:12:00Z',
  },
  {
    id: 'sell_ceramica',
    platform_id: 'plat_marisqueira',
    display_name: 'Cerâmica do Vale',
    kyc_status: 'verified',
    payout_currency: 'EUR',
    created_at: '2026-01-06T14:41:00Z',
  },
];

export const sampleCharge: Charge = {
  id: 'chg_0001',
  platform_id: 'plat_marisqueira',
  seller_id: 'sell_atelier',
  amount: money(12000, 'EUR'), // €120.00
  platform_fee: money(348, 'EUR'), // €3.48
  processor_fee: money(205, 'EUR'), // €2.05
  status: 'settled',
  idempotency_key: 'ik_chg_0001',
  processor_ref: 'ch_mock_3f9a1',
  created_at: '2026-02-11T10:05:12Z',
};

export const sampleCharges: Charge[] = [
  sampleCharge,
  {
    id: 'chg_0003',
    platform_id: 'plat_marisqueira',
    seller_id: 'sell_atelier',
    amount: money(8900, 'EUR'),
    platform_fee: money(258, 'EUR'),
    processor_fee: money(163, 'EUR'),
    status: 'partially_refunded',
    idempotency_key: 'ik_chg_0003',
    processor_ref: 'ch_mock_9d1e8',
    created_at: '2026-02-13T08:47:03Z',
  },
];

export const samplePayoutBatches: PayoutBatch[] = [
  {
    id: 'pyt_0001',
    seller_id: 'sell_atelier',
    amount: money(11447, 'EUR'), // seller net for chg_0001
    status: 'paid',
    scheduled_for: '2026-02-15T00:00:00Z',
    processor_ref: 'po_mock_5c8b2',
    created_at: '2026-02-14T22:00:00Z',
  },
];

export const sampleDisputes: Dispute[] = [
  {
    id: 'dsp_0001',
    charge_id: 'chg_0002',
    amount: money(4500, 'EUR'),
    status: 'open',
    created_at: '2026-02-16T09:03:22Z',
  },
];
