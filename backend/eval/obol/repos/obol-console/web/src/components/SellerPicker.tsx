/**
 * SellerPicker — dropdown of the platform's sellers, used by the Balance and
 * Payouts screens to choose which seller to inspect.
 */
import type { Seller } from '@obol/contracts';

export interface SellerPickerProps {
  sellers: Seller[];
  value: string | null;
  onChange: (sellerId: string) => void;
  label?: string;
}

export function SellerPicker({ sellers, value, onChange, label = 'Seller' }: SellerPickerProps): JSX.Element {
  return (
    <label className="seller-picker">
      {label}
      <select value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
        <option value="" disabled>
          Select a seller…
        </option>
        {sellers.map((s) => (
          <option key={s.id} value={s.id}>
            {s.display_name} ({s.id})
          </option>
        ))}
      </select>
    </label>
  );
}
