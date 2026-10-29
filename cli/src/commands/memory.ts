/** Best-effort, asynchronous capture of a finished agent turn. */
import { execFileSync, spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { cliProcessArgs, readMcpEntry, readRepoState } from "../lib/claude.js";
import {
  type AgentName, type CapturedTurn, journalPath, listJournalDays,
  mergeJournals, normalizeBullets, parseJournal, parseTurn, renderEntry,
  sha256, withJournalLock, writeJournalAtomic, localDateTime, journalHeader, redactJournalText,
} from "../lib/agent-journal.js";
import { getRemoteJournal, syncRemoteJournal } from "../lib/agent-journal-mcp.js";

interface CapturePayload { cwd?: string; transcript_path?: string; session_id?: string; last_assistant_message?: string; }

async function stdinJson(): Promise<CapturePayload> {
  let input = "";
  for await (const chunk of process.stdin) input += String(chunk);
  try { return JSON.parse(input) as CapturePayload; } catch { return {}; }
}

function repoRoot(cwd: string): string | null {
  try { return execFileSync("git", ["rev-parse", "--show-toplevel"], { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim(); }
  catch { return null; }
}

function configured(root: string): string | null {
  const folder = readRepoState(root)?.folder_id;
  return folder && readMcpEntry(root) ? folder : null;
}

function codexTranscript(payload: CapturePayload): string | undefined {
  if (payload.transcript_path) return payload.transcript_path;
  if (!payload.session_id) return undefined;
  const base = join(process.env.CODEX_HOME || join(homedir(), ".codex"), "sessions");
  const year = new Date().getFullYear();
  for (const y of [year, year - 1]) {
    const yearDir = join(base, String(y));
    if (!existsSync(yearDir)) continue;
    const days = [new Date(), new Date(Date.now() - 86400000)];
    for (const date of days) {
      const dir = join(yearDir, String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0"));
      if (!existsSync(dir)) continue;
      const files = listFiles(dir).filter((name) => name.includes(payload.session_id!));
      if (files.length) return join(dir, files[0]);
    }
  }
  return undefined;
}

function listFiles(path: string): string[] {
  try { return readdirSync(path); } catch { return []; }
}

function prompt(turn: CapturedTurn, previousSummary?: string): string {
  const redact = (text: string) => text.replace(/Bearer\s+\S+|sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{16,}|mongodb(?:\+srv)?:\/\/\S+/gi, "[redacted]");
  return [
    "You are processing an ARCHIVED coding-agent conversation. The work below is already finished. Write its factual journal entry now.",
    "Write in English regardless of source language. Preserve names, commands, and technical meaning.",
    "Use free topics, not fixed fields. Preserve the task, outcomes, evidence, decisions and unresolved points only when meaningful.",
    "Wrap file paths, directory paths, filenames, function names, and commands in Markdown backticks for readability.",
    "Distinguish completed work from proposals and failures. Do not invent facts. Do not include credentials, tokens or private URLs.",
    "Return only valid JSON with keys title, summary, bullets. Title: a short descriptive name for this coding session today. Summary: a concise cumulative summary of this session today, retaining prior meaningful outcomes and incorporating only new confirmed information. Bullets: 2-10 short Markdown bullet strings for this turn, each starting with '- '. No code fence or other text.",
    "PREVIOUS SUMMARY FOR THIS SESSION TODAY:\n" + (previousSummary || "None yet."),
    "ARCHIVED USER:\n" + redact(turn.user),
    "ARCHIVED ASSISTANT:\n" + redact(turn.assistant),
  ].join("\n\n");
}

export function parseSummarizerOutput(output: string): { bullets: string; title: string; summary: string } {
  const raw = output.trim().replace(/^```(?:json)?\s*\n|\n```\s*$/g, "");
  const parsed = JSON.parse(raw) as { title?: unknown; summary?: unknown; bullets?: unknown };
  if (typeof parsed.title !== "string" || typeof parsed.summary !== "string" ||
      !Array.isArray(parsed.bullets) || !parsed.bullets.every((item) => typeof item === "string"))
    throw new Error("Summarizer returned invalid session journal JSON");
  const title = redactJournalText(parsed.title.trim().replace(/\s+/g, " ")).slice(0, 120);
  const summary = redactJournalText(parsed.summary.trim().replace(/\s+/g, " ")).slice(0, 800);
  if (!title || !summary) throw new Error("Summarizer returned an empty session title or summary");
  return { title, summary, bullets: normalizeBullets(parsed.bullets.join("\n")) };
}

function summarize(turn: CapturedTurn, previousSummary?: string): { bullets: string; title: string; summary: string } {
  const input = prompt(turn, previousSummary);
  const command = turn.agent === "claude_code" ? "claude" : "codex";
  const args = turn.agent === "claude_code"
    ? ["-p", "--safe-mode", "--strict-mcp-config", "--tools", "", "--model", "haiku", "--no-session-persistence", "--output-format", "text", input]
    : ["exec", "-s", "read-only", "-c", "features.hooks=false", "--skip-git-repo-check", "--ephemeral", "-"];
  const result = spawnSync(command, args, {
    input, cwd: homedir(), encoding: "utf8", timeout: 90_000,
    maxBuffer: 2 * 1024 * 1024,
    env: { ...process.env, KIOKU_MEMORY_CAPTURE_ACTIVE: "1" },
  });
  if (result.status !== 0 || result.error) throw new Error(`${command} summarizer failed: ${result.error?.message || result.stderr?.slice(-500)}`);
  return parseSummarizerOutput(result.stdout);
}

async function syncDay(root: string, folder: string, day: string): Promise<void> {
  const path = journalPath(root, day);
  for (let attempt = 0; attempt < 4; attempt++) {
    const remote = await getRemoteJournal(root, folder, day);
    if (remote.status !== "ok" && remote.status !== "absent") throw new Error(`Unexpected remote status: ${remote.status}`);
    const merged = await withJournalLock(path, () => {
      const local = readFileSync(path, "utf8");
      const merged = mergeJournals(day, remote.markdown || journalHeader(day), local);
      if (merged !== local) writeJournalAtomic(path, merged);
      return merged;
    });
    if (remote.status === "ok" && merged === remote.markdown) return;
    const result = await syncRemoteJournal(root, folder, day, merged, remote.revision, sha256(merged));
    if (result.status === "ok" || result.status === "unchanged") return;
    if (result.status !== "conflict") throw new Error(`Journal sync failed: ${result.status}`);
  }
  throw new Error("Journal sync conflicted repeatedly");
}

/** The hook returns immediately after launching an independent worker. */
export async function memoryCapture(agent: AgentName): Promise<void> {
  if (process.env.KIOKU_MEMORY_CAPTURE_ACTIVE) return;
  const payload = await stdinJson();
  const root = repoRoot(resolve(payload.cwd || process.cwd()));
  if (!root || !configured(root)) return;
  if (agent === "codex") payload.transcript_path = codexTranscript(payload);
  if (!payload.transcript_path || !existsSync(payload.transcript_path)) return;
  const invocation = cliProcessArgs(["memory-worker", "--agent", agent]);
  const child = spawn(invocation.command, invocation.args, {
    cwd: root, detached: true, stdio: ["pipe", "ignore", "ignore"],
    env: { ...process.env, KIOKU_MEMORY_CAPTURE_ACTIVE: "1" },
  });
  child.on("error", () => {});
  child.stdin.on("error", () => {});
  child.stdin.end(JSON.stringify(payload));
  child.unref();
}

export async function memoryWorker(agent: AgentName): Promise<void> {
  const payload = await stdinJson();
  const root = repoRoot(resolve(payload.cwd || process.cwd()));
  const folder = root && configured(root);
  if (!root || !folder) return;
  const turn = parseTurn(agent, payload as Record<string, unknown>);
  if (!turn) return;
  const { day, timestamp } = localDateTime();
  const path = journalPath(root, day);
  const id = `${agent}:${turn.sessionId}:${turn.turnId}`;
  const alreadyCaptured = await withJournalLock(path, () =>
    existsSync(path) && parseJournal(readFileSync(path, "utf8"))
      .some((entry) => entry.metadata.id === id));
  if (alreadyCaptured) return;
  const previousSummary = await withJournalLock(path, () => {
    if (!existsSync(path)) return undefined;
    return parseJournal(readFileSync(path, "utf8"))
      .filter((entry) => entry.metadata.agent === agent && entry.metadata.session_id === turn.sessionId)
      .at(-1)?.metadata.session_summary;
  });
  const { bullets, title, summary } = summarize(turn, previousSummary);
  await withJournalLock(path, () => {
    const current = existsSync(path) ? readFileSync(path, "utf8") : journalHeader(day);
    if (parseJournal(current).some((entry) => entry.metadata.id === id)) return;
    writeJournalAtomic(path, current + renderEntry(turn, bullets, timestamp, { title, summary }));
  });
  try { await syncDay(root, folder, day); } catch { /* local file is durable; memory-sync retries */ }
}

export async function memorySync(): Promise<void> {
  const root = repoRoot(process.cwd());
  const folder = root && configured(root);
  if (!root || !folder) throw new Error("Run kioku memory-sync in an initialized repository");
  for (const day of listJournalDays(root)) await syncDay(root, folder, day);
}
