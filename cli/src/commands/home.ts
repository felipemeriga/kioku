// cli/src/commands/home.ts
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { readConfig } from "../lib/config.js";
import { whoami } from "../lib/api.js";
import { detectGit } from "../lib/git.js";
import { selectAction, promptText } from "../ui/menu.js";
import { buildMenu, type HomeAction, type HomeState } from "../ui/home.js";
import { brand, sym } from "../ui/theme.js";
import { ls } from "./ls.js";
import { search } from "./search.js";
import { briefing } from "./briefing.js";
import { init } from "./init.js";
import { status } from "./status.js";
import { doctor } from "./doctor.js";
import { login } from "./login.js";
import { logout } from "./logout.js";

// Correction 1: init takes (cwd, opts), not ({})
// Correction 2: await logout() — logout is async
export const HOME_ACTIONS: Record<Exclude<HomeAction, "quit">, () => Promise<void>> = {
  ls: () => ls(undefined, {}),
  search: async () => { const q = await promptText("Search query"); if (q.trim()) await search(q, {}); },
  briefing: () => briefing({}),
  init: () => init(process.cwd(), {}),
  status: () => status(),
  doctor: () => doctor(),
  login: () => login({}),
  logout: async () => { await logout(); },
};

async function readState(): Promise<HomeState> {
  const cfg = readConfig();
  const signedIn = !!cfg.access_token;
  const repoRoot = resolve(process.cwd());
  const git = detectGit(repoRoot);
  const repoWired = existsSync(join(repoRoot, ".mcp.json"));
  let rootFolders: number | undefined;
  if (signedIn) {
    try { rootFolders = (await whoami()).root_folders.length; } catch { /* offline is fine */ }
  }
  return {
    signedIn, email: cfg.email, rootFolders, apiBase: cfg.api_base,
    inRepo: git.isRepo, repoWired,
  };
}

function header(s: HomeState): void {
  console.log();
  console.log(`  ${brand.primary(sym.mark)}  ${brand.secondary("Kioku")} ${brand.muted("キオク")}`);
  console.log(`  ${brand.muted("─".repeat(42))}`);
  if (s.signedIn) {
    console.log(`  ${brand.primary(sym.dot)} signed in   ${s.email ?? ""}`);
    console.log(`  ${brand.primary(sym.dot)} workspace   ${s.rootFolders ?? "?"} root folders · ${brand.muted(s.apiBase)}`);
  } else {
    console.log(`  ${brand.muted(sym.dot)} not signed in   ${brand.muted(s.apiBase)}`);
  }
  console.log();
}

export async function runHome(): Promise<void> {
  for (;;) {
    const state = await readState();
    header(state);
    const items = buildMenu(state);
    let action: HomeAction;
    try {
      action = await selectAction<HomeAction>("What do you want to do?", items);
    } catch {
      return; // Ctrl-C / Esc
    }
    if (action === "quit") return;
    try {
      await HOME_ACTIONS[action]();
    } catch (err) {
      const { printError } = await import("../lib/banner.js");
      printError(err);
    }
    console.log();
  }
}
