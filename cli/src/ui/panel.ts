import boxen from "boxen";
import { colorEnabled, brand, termWidth } from "./theme.js";

type Tone = "default" | "success" | "warn" | "error";
const toneColor: Record<Tone, (s: string) => string> = {
  default: brand.secondary,
  success: (s) => `\x1b[32m${s}\x1b[39m`,
  warn: (s) => `\x1b[33m${s}\x1b[39m`,
  error: (s) => `\x1b[31m${s}\x1b[39m`,
};

export function panel(opts: { title?: string; body: string; tone?: Tone }): string {
  const tone = opts.tone ?? "default";
  if (!colorEnabled()) {
    // Plain, stable fallback for pipes/CI/hooks.
    const head = opts.title ? `${opts.title}\n` : "";
    return `${head}${opts.body}`;
  }
  return boxen(opts.body, {
    title: opts.title ? toneColor[tone](opts.title) : undefined,
    padding: { top: 0, bottom: 0, left: 1, right: 1 },
    margin: { top: 0, bottom: 0, left: 1, right: 0 },
    borderStyle: "round",
    borderColor: tone === "default" ? "cyan" : tone === "success" ? "green" : tone === "warn" ? "yellow" : "red",
    width: Math.min(termWidth() - 2, 76),
  });
}
