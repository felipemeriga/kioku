// cli/src/ui/theme.ts
/** Single source of truth for CLI presentation gating + brand. */

export function colorEnabled(): boolean {
  return (
    !process.env.NO_COLOR &&
    !process.env.KIOKU_NO_COLOR &&
    process.stdout.isTTY === true
  );
}

export function isQuiet(): boolean {
  return !!process.env.KIOKU_QUIET;
}

/** True only for a real interactive terminal (drives menus/spinners). */
export function isInteractive(): boolean {
  return process.stdout.isTTY === true && !process.env.KIOKU_QUIET;
}

function fg(r: number, g: number, b: number) {
  return (s: string) =>
    colorEnabled() ? `\x1b[38;2;${r};${g};${b}m${s}\x1b[39m` : s;
}

export const brand = {
  primary: fg(255, 121, 63),   // orange
  secondary: fg(148, 214, 219), // cyan
  accent: fg(178, 154, 248),   // violet
  muted: fg(120, 122, 130),    // dim
};

const GLYPH = { ok: "✓", bad: "✗", warn: "!", dot: "●", repo: "◆", folder: "▸", arrow: "❯", mark: "記" };
const ASCII = { ok: "[ok]", bad: "[x]", warn: "[!]", dot: "*", repo: "#", folder: "-", arrow: ">", mark: "K" };

/** Lazy getter so KIOKU_ASCII is read at access time (test-friendly). */
export const sym: typeof GLYPH = new Proxy(GLYPH, {
  get(_t, k: string) {
    return (process.env.KIOKU_ASCII ? ASCII : GLYPH)[k as keyof typeof GLYPH];
  },
}) as typeof GLYPH;

export function termWidth(): number {
  return process.stdout.columns && process.stdout.columns > 0
    ? process.stdout.columns
    : 80;
}
