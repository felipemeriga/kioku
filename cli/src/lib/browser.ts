import { execFileSync } from "node:child_process";

/** Best-effort browser open. macOS: open, Linux: xdg-open, Windows: start. */
export function tryOpenBrowser(url: string): void {
  const cmd =
    process.platform === "darwin"
      ? ["open", url]
      : process.platform === "win32"
      ? ["cmd", "/c", "start", url]
      : ["xdg-open", url];
  try {
    execFileSync(cmd[0], cmd.slice(1), { stdio: "ignore", timeout: 2000 });
  } catch {
    // No browser (headless server, WSL edge cases). Caller already printed the URL.
  }
}
