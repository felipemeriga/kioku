import Table from "cli-table3";
import { colorEnabled, brand } from "./theme.js";

export function renderTable(headers: string[], rows: string[][]): string {
  if (!colorEnabled()) {
    // Aligned plain columns for pipes/CI/hooks.
    const widths = headers.map((h, i) =>
      Math.max(h.length, ...rows.map((r) => (r[i] ?? "").length)),
    );
    const fmt = (cells: string[]) =>
      cells.map((c, i) => (c ?? "").padEnd(widths[i])).join("  ").trimEnd();
    return [fmt(headers), ...rows.map(fmt)].join("\n");
  }
  const t = new Table({
    head: headers.map((h) => brand.secondary(h)),
    style: { head: [], border: [] },
    chars: { mid: "", "left-mid": "", "mid-mid": "", "right-mid": "" },
  });
  for (const r of rows) t.push(r);
  return t.toString();
}
