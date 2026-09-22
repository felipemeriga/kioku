/**
 * Shared per-ROOT api key store — ~/.config/kioku/root-keys.json (0600).
 *
 * A kioku api key is scoped to a folder. To let a coding session in ANY repo
 * under a root search/reference ALL repos under that root (the cross-app
 * interaction that per-repo keys break), every repo of a root shares ONE
 * root-scoped key. Claude Code has no shared config (each repo has its own
 * .mcp.json), so this file is where that shared root key lives — keyed by the
 * root folder id. Codex could use its global config, but keying both surfaces
 * here keeps one source of truth and avoids re-minting (which would revoke the
 * one-key-per-scope key and 401 sibling repos).
 */

import {
  chmodSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { configDir } from "./config.js";

export interface RootKeyEntry {
  key: string;
  url: string;
  headers: Record<string, string>;
}

function storePath(): string {
  return join(configDir(), "root-keys.json");
}

function readStore(): Record<string, RootKeyEntry> {
  const p = storePath();
  if (!existsSync(p)) return {};
  try {
    return JSON.parse(readFileSync(p, "utf8")) as Record<string, RootKeyEntry>;
  } catch {
    return {};
  }
}

/** The shared root-scoped key for this root, if one has been minted. */
export function getRootKey(rootId: string): RootKeyEntry | null {
  return readStore()[rootId] ?? null;
}

/** Persist the root-scoped key so every repo of this root reuses it. */
export function saveRootKey(rootId: string, entry: RootKeyEntry): void {
  const dir = configDir();
  if (!existsSync(dir)) mkdirSync(dir, { recursive: true, mode: 0o700 });
  const store = readStore();
  store[rootId] = entry;
  const p = storePath();
  writeFileSync(p, JSON.stringify(store, null, 2), { mode: 0o600 });
  try {
    chmodSync(p, 0o600);
  } catch {
    // Best-effort — Windows FS may not support chmod.
  }
}
