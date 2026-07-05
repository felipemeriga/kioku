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

// kleur doesn't ship rgb(), so we render via ANSI 24-bit escapes directly.
// Modern terminals (iTerm, macOS Terminal, Windows Terminal, VS Code)
// all support truecolor; older ones degrade to the nearest 256-color.
const fg = (r: number, g: number, b: number) => (s: string) =>
  `\x1b[38;2;${r};${g};${b}m${s}\x1b[39m`;

const ORANGE = fg(255, 121, 63);
const CYAN = fg(148, 214, 219);
const VIOLET = fg(178, 154, 248);
const DIM = fg(120, 122, 130);

export const brand = {
  primary: ORANGE,
  secondary: CYAN,
  accent: VIOLET,
  muted: DIM,
};

/** Small, restrained banner that only prints on interactive commands. */
export function banner(): void {
  if (process.env.AGENTIC_RAG_QUIET) return;
  const dot = ORANGE("●");
  const line = DIM("─".repeat(40));
  console.log();
  console.log(`  ${dot} ${kleur.bold("agentic-rag")}  ${DIM("second-brain for coding agents")}`);
  console.log(`  ${line}`);
  console.log();
}

/** Section heading with a soft rule under it. */
export function section(title: string): void {
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
  console.log(`  ${DIM("·")} ${DIM(msg)}`);
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
