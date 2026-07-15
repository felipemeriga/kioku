// cli/src/commands/login.ts
import { hostname } from "node:os";
import kleur from "kleur";
import { deviceStart, devicePoll, whoami } from "../lib/api.js";
import { readConfig, writeConfig } from "../lib/config.js";
import { tryOpenBrowser } from "../lib/browser.js";
import { box, info, section } from "../lib/banner.js";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function login(opts: { noBrowser?: boolean } = {}): Promise<void> {
  const cfg = readConfig();
  section("Sign in");
  info(`API: ${cfg.api_base}`);

  const start = await deviceStart(hostname(), process.platform);

  console.log();
  info("Open this URL in your browser to authorize:");
  console.log("    " + kleur.bold(kleur.cyan(start.verification_url)));
  console.log();
  if (!opts.noBrowser) tryOpenBrowser(start.verification_url);
  process.stdout.write(kleur.dim("  · Waiting for authorization"));

  const deadline = Date.now() + start.expires_in * 1000;
  while (Date.now() < deadline) {
    const result = await devicePoll(start.device_code);
    if (result.status === "authorized" && result.tokens) {
      const t = result.tokens;
      writeConfig({
        ...cfg,
        access_token: t.access_token,
        refresh_token: t.refresh_token,
        expires_at: t.expires_at,
        user_id: t.user.id,
        email: t.user.email,
      });
      console.log();
      const w = await whoami();
      box([
        `${kleur.green("✓")} ${kleur.bold("Signed in")}`,
        kleur.dim(`  ${t.user.email}`),
        kleur.dim(`  ${w.root_folders.length} root folder${w.root_folders.length === 1 ? "" : "s"}`),
      ]);
      console.log();
      info("Next: cd into a repo and run " + kleur.bold("kioku init"));
      return;
    }
    if (result.status === "denied") {
      console.log();
      throw new Error("Login was denied in the browser.");
    }
    if (result.status === "expired") {
      console.log();
      throw new Error("Login link expired. Run kioku login again.");
    }
    process.stdout.write(kleur.dim("."));
    await sleep(start.interval * 1000);
  }
  console.log();
  throw new Error("Timed out waiting for authorization. Run kioku login again.");
}
