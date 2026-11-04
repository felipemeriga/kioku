/** Read-only capability diagnostics. Never starts an agent session or model. */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { parse } from "smol-toml";
import { codexConfigPath } from "./codex.js";

export const EVIDENCE_HOOK_EVENTS = [
  "SessionStart",
  "PostToolUse",
  "Stop",
  "SubagentStart",
  "SubagentStop",
  "PreCompact",
  "SessionEnd",
] as const;
function version(binary: string): string | null {
  try {
    return (
      execFileSync(binary, ["--version"], {
        encoding: "utf8",
        timeout: 1500,
        stdio: ["ignore", "pipe", "ignore"],
      })
        .trim()
        .match(/\d+\.\d+\.\d+/)?.[0] || null
    );
  } catch {
    return null;
  }
}
export function evidenceHookCapabilities(
  root: string,
  versions?: { claude_code: string | null; codex: string | null },
): Record<string, unknown> {
  const installed = versions || {
    claude_code: version("claude"),
    codex: version("codex"),
  };
  return Object.fromEntries(
    (["claude_code", "codex"] as const).map((agent) => {
      const audited = agent === "codex" ? "0.165.0" : "2.1.285";
      const detected = installed[agent],
        supported = detected === audited;
      let hooks: Record<string, unknown> = {},
        disabled = false,
        parseError = false;
      try {
        if (agent === "codex") {
          const config = parse(readFileSync(codexConfigPath(), "utf8"));
          hooks = (config.hooks as Record<string, unknown>) || {};
        } else {
          for (const path of [
            join(
              process.env.CLAUDE_CONFIG_DIR || join(homedir(), ".claude"),
              "settings.json",
            ),
            join(root, ".claude", "settings.json"),
            join(root, ".claude", "settings.local.json"),
          ]) {
            try {
              const config = JSON.parse(readFileSync(path, "utf8"));
              hooks = { ...hooks, ...config.hooks };
              if (config.disableAllHooks === true) disabled = true;
            } catch (error) {
              if ((error as NodeJS.ErrnoException).code !== "ENOENT")
                parseError = true;
            }
          }
        }
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT")
          parseError = true;
      }
      const configured = EVIDENCE_HOOK_EVENTS.filter((event) =>
        JSON.stringify(hooks[event] || []).includes(
          "evidence-capture --agent " + agent,
        ),
      );
      const reason = !detected
        ? "cli_unavailable"
        : !supported
          ? "version_not_audited"
          : parseError
            ? "configuration_unreadable"
            : disabled
              ? "hooks_disabled"
              : configured.length !== EVIDENCE_HOOK_EVENTS.length
                ? "hooks_missing"
                : null;
      return [
        agent,
        {
          version: detected,
          schema_status: supported ? "verified" : "unverified",
          audited_version: audited,
          supported_events: supported ? EVIDENCE_HOOK_EVENTS : [],
          configured_events: configured,
          missing_events: EVIDENCE_HOOK_EVENTS.filter(
            (event) => !configured.includes(event),
          ),
          capture_status: reason ? "degraded" : "configured",
          reason,
          hook_trust:
            agent === "codex"
              ? "host_confirmation_required_or_previously_granted"
              : "subject_to_workspace_and_managed_policy",
          runtime_execution_verified: false,
          recovery:
            "Run kioku init to install missing hooks; evidence-sync retries registered local sources. Hook trust and managed policy remain controlled by the host.",
        },
      ];
    }),
  );
}
