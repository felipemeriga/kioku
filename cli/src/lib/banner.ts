/**
 * Visual system matching Claude Code's terminal aesthetic:
 * - Compact orange/blue two-tone banner
 * - Boxed panels with rounded corners
 * - "✻" prefix on prompts, "✓" on success, "✗" on error
 * - Muted separators (`─`) and subtle dim text between actions
 *
 * Feedback primitives use kleur; the richer ui/ toolkit (panels/tables)
 * adds boxen + cli-table3.
 */

import kleur from "kleur";
import { colorEnabled, isQuiet, brand as _brand } from "../ui/theme.js";

export { brand } from "../ui/theme.js";

// Local aliases for brevity — functions read colorEnabled() lazily on each call.
const ORANGE = _brand.primary;
const CYAN = _brand.secondary;
const VIOLET = _brand.accent;
const DIM = _brand.muted;

// Sync kleur's own coloring with our flag — re-read on every call site
// via getter. kleur only checks `enabled` at each color-fn invocation.
Object.defineProperty(kleur, "enabled", {
  get(): boolean {
    return colorEnabled();
  },
  configurable: true,
});

/** Small, restrained banner that only prints on interactive commands. */
export function banner(): void {
  if (isQuiet()) return;
  const dot = ORANGE("●");
  const line = DIM("─".repeat(40));
  console.log();
  console.log(`  ${dot} ${kleur.bold("kioku")} ${DIM("記憶")}  ${DIM("second brain for your repos")}`);
  console.log(`  ${line}`);
  console.log();
}

/** Section heading with a soft rule under it. */
export function section(title: string): void {
  if (isQuiet()) return;
  console.log();
  console.log(`  ${VIOLET("│")} ${kleur.bold(title)}`);
  console.log(`  ${DIM("│")}`);
}

/** Rendered as `  ✓ <msg>` with a green check. */
export function ok(msg: string, hint?: string): void {
  console.log(
    `  ${kleur.green("✓")} ${msg}${hint ? "  " + DIM(hint) : ""}`,
  );
}
export function warn(msg: string, hint?: string): void {
  console.log(
    `  ${kleur.yellow("!")} ${msg}${hint ? "  " + DIM(hint) : ""}`,
  );
}
export function bad(msg: string, hint?: string): void {
  console.log(
    `  ${kleur.red("✗")} ${msg}${hint ? "  " + DIM(hint) : ""}`,
  );
}
export function info(msg: string): void {
  if (isQuiet()) return;
  console.log(`  ${DIM("·")} ${DIM(msg)}`);
}

/**
 * Pretty-print an ApiError (or any error) with an actionable hint.
 * Keeps the exit path in each command handler to a single line.
 */
export function printError(err: unknown): void {
  const msg = err instanceof Error ? err.message : String(err);
  console.log();
  console.log(`  ${kleur.red("✗")} ${msg}`);
  const anyErr = err as { hint?: string };
  if (anyErr?.hint) {
    console.log(`    ${DIM(anyErr.hint)}`);
  }
  console.log();
}

/**
 * Long-running work indicator. Prints "  ⋯ msg" and returns a function
 * that erases the line and prints "  ✓ msg" (or "  ✗ msg" on error). We
 * don't take an `ora` dependency because a single spinner char is enough
 * for our 2-5s calls and it keeps the binary tiny.
 */
export async function step<T>(msg: string, fn: () => Promise<T>): Promise<T> {
  const isTTY = process.stdout.isTTY;
  const frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
  let i = 0;
  const start = Date.now();
  const draw = (frame: string) => {
    if (!isTTY) return;
    process.stdout.write(`\r  ${VIOLET(frame)} ${msg}`);
  };
  const timer = isTTY
    ? setInterval(() => {
        i = (i + 1) % frames.length;
        draw(frames[i]);
      }, 90)
    : null;
  if (!isTTY) console.log(`  ${DIM("·")} ${DIM(msg)}`);
  else draw(frames[0]);
  try {
    const result = await fn();
    if (timer) clearInterval(timer);
    if (isTTY) {
      const elapsed = Date.now() - start;
      const suffix = elapsed > 800 ? DIM(`  (${Math.round(elapsed / 100) / 10}s)`) : "";
      process.stdout.write(
        `\r  ${kleur.green("✓")} ${msg}${suffix}\x1b[K\n`,
      );
    }
    return result;
  } catch (err) {
    if (timer) clearInterval(timer);
    if (isTTY) process.stdout.write(`\r  ${kleur.red("✗")} ${msg}\x1b[K\n`);
    throw err;
  }
}

/** For the boxed panel around the "logged in" success state. */
export function box(lines: string[]): void {
  const width = Math.max(...lines.map((l) => stripAnsi(l).length));
  const top = DIM("╭" + "─".repeat(width + 2) + "╮");
  const bottom = DIM("╰" + "─".repeat(width + 2) + "╯");
  const side = DIM("│");
  console.log("  " + top);
  for (const line of lines) {
    const pad = " ".repeat(width - stripAnsi(line).length);
    console.log(`  ${side} ${line}${pad} ${side}`);
  }
  console.log("  " + bottom);
}

function stripAnsi(s: string): string {
  // eslint-disable-next-line no-control-regex
  return s.replace(/\x1b\[[0-9;]*m/g, "");
}
