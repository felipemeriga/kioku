import kleur from "kleur";
import { readConfig, clearAuth } from "../lib/config.js";
import { ok, section, info } from "../lib/banner.js";

export async function logout(): Promise<void> {
  const cfg = readConfig();
  section("Sign out");
  if (!cfg.access_token) {
    info("Not signed in — nothing to do.");
    return;
  }
  clearAuth();
  ok(`Signed out ${cfg.email ? kleur.dim("(" + cfg.email + ")") : ""}`);
  info("Run: kioku login  to sign back in.");
}
