import { input } from "@inquirer/prompts";
import kleur from "kleur";
import { sendOtp, verifyOtp, whoami } from "../lib/api.js";
import { readConfig, writeConfig } from "../lib/config.js";
import { box, info, ok, section } from "../lib/banner.js";

export async function login(): Promise<void> {
  const cfg = readConfig();
  section("Sign in");
  info(`API: ${cfg.api_base}`);

  const email = await input({
    message: "Email",
    validate: (v) =>
      /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v) || "Please enter a valid email.",
  });

  process.stdout.write(kleur.dim("  · Sending code… "));
  await sendOtp(email);
  console.log(kleur.dim("done."));

  const token = await input({
    message: "6-digit code from email",
    validate: (v) =>
      /^\d{6,10}$/.test(v.trim()) || "The code is 6-10 digits.",
  });

  const res = await verifyOtp(email, token.trim());
  writeConfig({
    ...cfg,
    access_token: res.access_token,
    refresh_token: res.refresh_token,
    expires_at: res.expires_at,
    user_id: res.user.id,
    email: res.user.email,
  });

  const w = await whoami();
  console.log();
  box([
    `${kleur.green("✓")} ${kleur.bold("Signed in")}`,
    kleur.dim(`  ${res.user.email}`),
    kleur.dim(`  ${w.root_folders.length} root folder${w.root_folders.length === 1 ? "" : "s"}`),
  ]);
  console.log();
  info("Next: cd into a repo and run " + kleur.bold("agentic-rag init"));
  console.log();
}
