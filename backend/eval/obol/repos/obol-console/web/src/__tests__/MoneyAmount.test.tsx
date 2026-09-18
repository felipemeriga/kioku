import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { money } from '@obol/contracts';
import { MoneyAmount } from '../components/MoneyAmount.js';

describe('MoneyAmount', () => {
  it('formats €120.00 from { 12000, EUR } (spec chg_0001)', () => {
    render(<MoneyAmount value={money(12000, 'EUR')} />);
    expect(screen.getByText('€120.00')).toBeInTheDocument();
  });

  it('exposes raw minor units on the element for auditing', () => {
    render(<MoneyAmount value={money(348, 'EUR')} />);
    const el = screen.getByText('€3.48');
    expect(el).toHaveAttribute('data-amount-minor', '348');
    expect(el).toHaveAttribute('data-currency', 'EUR');
  });

  it('marks negative amounts and prefixes a sign when signed', () => {
    render(<MoneyAmount value={money(-500, 'EUR')} signed />);
    const el = screen.getByText('-€5.00');
    expect(el).toHaveClass('money--negative');
  });
});
