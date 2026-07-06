/**
 * `kioku briefing` — view the current repo's briefing right in
 * the terminal. This is the same content Claude Code sees at session
 * start via get_folder_briefing().
 *
 * Reads .claude/kioku-state.json to know which folder to fetch.
 * Renders each section with a status chip and clean formatting.
 */

import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import kleur from "kleur";
import { fetchBriefing, type BriefingSection } from "../lib/api.js";
import { section as sectionHeading, info, ok, warn } from "../lib/banner.js";

interface Opts {
  json?: boolean;
  section?: string;
}

const SECTION_ORDER = [
  "overview",
  "architecture",
  "preferences",
  "important_files",
  "how_it_runs",
  "deployment",
  "dependencies",
  "activity",
] as const;

const SECTION_TITLES: Record<string, string> = {
  overview: "Overview",
  architecture: "Architecture",
  preferences: "Preferences",
  important_files: "Important files",
  how_it_runs: "How it runs",
  deployment: "Deployment",
  dependencies: "Dependencies",
  activity: "Activity",
};

export async function briefing(opts: Opts): Promise<void> {
  const repoRoot = resolve(process.cwd());
  const statePath = join(repoRoot, ".claude", "kioku-state.json");
  if (!existsSync(statePath)) {
    warn(
      "This repo hasn't been initialized.",
      "Run: kioku init",
    );
    process.exitCode = 1;
    return;
  }
  const state = JSON.parse(readFileSync(statePath, "utf8")) as {
    folder_id: string;
    folder_name: string;
  };
  const b = await fetchBriefing(state.folder_id);

  if (opts.json) {
    if (opts.section) {
      const s = b.sections[opts.section];
      if (!s) throw new Error(`No section '${opts.section}'.`);
      console.log(JSON.stringify(s, null, 2));
      return;
    }
    console.log(JSON.stringify(b, null, 2));
    return;
  }

  // Pretty text output
  sectionHeading(`Briefing · ${b.folder.name}  ${kleur.dim(
    "(" + b.folder.kind + " · " + (b.folder.id.slice(0, 8)) + "…)",
  )}`);
  info(
    b.last_generated_at
      ? `Last generated ${formatRelative(new Date(b.last_generated_at))}`
      : "No prior generation",
  );
  console.log();

  // If the user asked for a specific section, validate it BEFORE
  // rendering so a typo produces an actionable error instead of silent
  // success with no output.
  if (opts.section && !SECTION_ORDER.includes(opts.section as (typeof SECTION_ORDER)[number])) {
    throw new Error(
      `Unknown section '${opts.section}'. Valid: ${SECTION_ORDER.join(", ")}`,
    );
  }
  const keys = opts.section ? [opts.section] : SECTION_ORDER;
  for (const key of keys) {
    const s = b.sections[key];
    if (!s) continue;
    printSection(key, s);
  }

  console.log();
  info(
    "Edit a section: kioku briefing --section <name> --json  |  or edit in the web UI.",
  );
}

function printSection(key: string, s: BriefingSection): void {
  const title = SECTION_TITLES[key] ?? key;
  console.log(
    `  ${kleur.bold(title)}  ${statusChip(s.status)} ${kleur.dim(
      "· " + provenanceLabel(s.provenance),
    )}`,
  );
  const rendered = renderContent(s.content);
  if (rendered.trim() === "") {
    console.log("    " + kleur.dim("(not filled in yet)"));
  } else {
    for (const line of rendered.split("\n")) {
      console.log("    " + line);
    }
  }
  console.log();
}

function statusChip(status: BriefingSection["status"]): string {
  switch (status) {
    case "pinned":
      return kleur.bgYellow(kleur.black(" PINNED "));
    case "hybrid":
      return kleur.bgCyan(kleur.black(" HYBRID "));
    default:
      return kleur.bgMagenta(kleur.black(" AUTO "));
  }
}

function provenanceLabel(p: BriefingSection["provenance"]): string {
  return p === "user_ui" ? "you (UI)" : p === "agent_mcp" ? "agent (MCP)" : "auto";
}

function renderContent(content: unknown): string {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((item) => {
        if (typeof item === "string") return "• " + item;
        if (item && typeof item === "object") {
          const obj = item as Record<string, unknown>;
          const parts: string[] = [];
          for (const [k, v] of Object.entries(obj)) {
            parts.push(`${kleur.cyan(k)}: ${String(v)}`);
          }
          return "• " + parts.join("  ");
        }
        return "• " + String(item);
      })
      .join("\n");
  }
  if (typeof content === "object") {
    const obj = content as Record<string, unknown>;
    const parts: string[] = [];
    for (const [k, v] of Object.entries(obj)) {
      const label = kleur.cyan(k);
      if (v == null || (typeof v === "string" && !v.trim())) {
        parts.push(`${label}: ${kleur.dim("(empty)")}`);
      } else if (Array.isArray(v)) {
        parts.push(label + ":");
        for (const item of v) {
          if (typeof item === "string") parts.push("  • " + item);
          else parts.push("  • " + JSON.stringify(item));
        }
      } else if (typeof v === "object") {
        parts.push(label + ": " + JSON.stringify(v));
      } else {
        parts.push(`${label}: ${String(v)}`);
      }
    }
    return parts.join("\n");
  }
  return String(content);
}

function formatRelative(d: Date): string {
  const s = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.floor(h / 24);
  return `${days}d ago`;
}
