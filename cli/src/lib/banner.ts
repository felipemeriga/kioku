/**
 * Visual system matching Claude Code's terminal aesthetic:
 * - Compact orange/blue two-tone banner
 * - Boxed panels with rounded corners
 * - "✻" prefix on prompts, "✓" on success, "✗" on error
 * - Muted separators (`─`) and subtle dim text between actions
 *
 * We use kleur (already a dep) — no chalk / boxen / cli-boxes needed
 * so the binary stays small and starts fast.
 */

import kleur from "kleur";

// NO_COLOR (https://no-color.org/) is the standard opt-out.
// AGENTIC_RAG_QUIET turns off the banner + info lines but leaves ok/warn/bad.
// AGENTIC_RAG_NO_COLOR is an app-specific override in case someone wants
// the CLI colored while other tools are muted (or vice versa).
//
// Both are read LAZILY at each call — commander's preAction hook sets
// them just before the command action runs, so a module-load cached
// value would be stale by the time we print anything.
function colorEnabled(): boolean {
  return (
    !process.env.NO_COLOR &&
    !process.env.AGENTIC_RAG_NO_COLOR &&
    process.stdout.isTTY === true
  );
}

function isQuiet(): boolean {
  return !!process.env.AGENTIC_RAG_QUIET;
}

const identity = (s: string) => s;

// Truecolor helper — silently degrades to no-op when colors are off.
function fg(r: number, g: number, b: number) {
  return (s: string) =>
    colorEnabled() ? `\x1b[38;2;${r};${g};${b}m${s}\x1b[39m` : s;
}

const ORANGE = fg(255, 121, 63);
const CYAN = fg(148, 214, 219);
const VIOLET = fg(178, 154, 248);
const DIM = fg(120, 122, 130);

// Sync kleur's own coloring with our flag — re-read on every call site
// via getter. kleur only checks `enabled` at each color-fn invocation.
Object.defineProperty(kleur, "enabled", {
  get(): boolean {
    return colorEnabled();
  },
  configurable: true,
});

export const brand = {
  primary: ORANGE,
  secondary: CYAN,
  accent: VIOLET,
  muted: DIM,
};

/** Small, restrained banner that only prints on interactive commands. */
export function banner(): void {
  if (isQuiet()) return;
  const dot = ORANGE("●");
  const line = DIM("─".repeat(40));
  console.log();
  console.log(`  ${dot} ${kleur.bold("agentic-rag")}  ${DIM("second-brain for coding agents")}`);
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
