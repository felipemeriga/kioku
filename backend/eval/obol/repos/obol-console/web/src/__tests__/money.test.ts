/**
 * Exercises the shared Money contract (SPEC §Money) used by both web and bff.
 */
import { describe, it, expect } from 'vitest';
import { addMoney, formatMoney, money, subtractMoney } from '@obol/contracts';

describe('Money contract', () => {
  it('rejects non-integer minor units', () => {
    expect(() => money(12.5, 'EUR')).toThrow();
  });

  it('formats the canonical spec charge: { 12000, EUR } → €120.00', () => {
    expect(formatMoney(money(12000, 'EUR'))).toBe('€120.00');
  });

  it('adds same-currency money', () => {
    expect(addMoney(money(348, 'EUR'), money(205, 'EUR'))).toEqual({
      amountMinor: 553,
      currency: 'EUR',
    });
  });

  it('rejects cross-currency arithmetic', () => {
    expect(() => addMoney(money(100, 'EUR'), money(100, 'USD'))).toThrow(/Cross-currency/);
  });

  it('computes seller net for chg_0001: 12000 - 348 - 205 = 11447', () => {
    const net = subtractMoney(subtractMoney(money(12000, 'EUR'), money(348, 'EUR')), money(205, 'EUR'));
    expect(net.amountMinor).toBe(11447);
  });
});
