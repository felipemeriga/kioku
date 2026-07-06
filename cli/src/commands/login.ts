import { input, select } from "@inquirer/prompts";
import kleur from "kleur";
import { sendOtp, verifyOtp, whoami, ApiError } from "../lib/api.js";
import { readConfig, writeConfig } from "../lib/config.js";
import { box, info, ok, section, warn } from "../lib/banner.js";

/**
 * Resilient sign-in.
 *
 * - Rate-limit on OTP send → tell the user how long to wait + offer to
 *   resend when the cooldown expires.
 * - Bad code → retry inline without re-sending the email.
 * - Expired code → resend + prompt again in place.
 */
export async function login(): Promise<void> {
  const cfg = readConfig();
  section("Sign in");
  info(`API: ${cfg.api_base}`);

  const email = await input({
    message: "Email",
    validate: (v) =>
      /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v) || "Please enter a valid email.",
  });

  await sendOtpWithRateLimitRecovery(email);

  let attempts = 0;
  while (true) {
    const token = await input({
      message:
        attempts === 0
          ? "6-digit code from email"
          : `Code (attempt ${attempts + 1}) — or type 'resend'`,
      validate: (v) => {
        const t = v.trim().toLowerCase();
        if (t === "resend" || t === "r") return true;
        return /^\d{6,10}$/.test(t) || "6-10 digits, or 'resend'.";
      },
    });

    const trimmed = token.trim().toLowerCase();
    if (trimmed === "resend" || trimmed === "r") {
      await sendOtpWithRateLimitRecovery(email);
      attempts = 0;
      continue;
    }

    try {
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
        kleur.dim(
          `  ${w.root_folders.length} root folder${w.root_folders.length === 1 ? "" : "s"}`,
        ),
      ]);
      console.log();
      info("Next: cd into a repo and run " + kleur.bold("kioku init"));
      console.log();
      return;
    } catch (err) {
      attempts += 1;
      const msg = err instanceof Error ? err.message : String(err);
      warn(`That code didn't work: ${msg.split("\n")[0]}`);
      if (attempts >= 3) {
        const choice = await select<"retry" | "resend" | "abort">({
          message: "Three bad codes in a row. Try again?",
          choices: [
            { name: "Resend a new code", value: "resend" },
            { name: "Try one more code", value: "retry" },
            { name: "Abort", value: "abort" },
          ],
        });
        if (choice === "abort") throw new Error("Login aborted after retries.");
        if (choice === "resend") {
          await sendOtpWithRateLimitRecovery(email);
        }
        attempts = 0;
      }
    }
  }
}

/**
 * Wraps sendOtp with rate-limit-aware retry.
 * Supabase returns 400 with 'you can only request this after N seconds' when
 * a fresh OTP was already sent recently. We parse that out and either
 * wait+retry or bail with a friendly message.
 */
async function sendOtpWithRateLimitRecovery(email: string): Promise<void> {
  process.stdout.write(kleur.dim("  · Sending code… "));
  try {
    await sendOtp(email);
    console.log(kleur.dim("done."));
    return;
  } catch (err) {
    console.log(kleur.dim("hit a rate limit."));
    const msg = err instanceof Error ? err.message : String(err);
    const secondsMatch = /after (\d+) seconds/i.exec(msg);
    const waitSec = secondsMatch ? parseInt(secondsMatch[1], 10) : null;

    // Common case: fresh send too soon. Users might have a code already —
    // ask before waiting.
    if (waitSec !== null && waitSec > 0) {
      info(
        `A code was sent recently. Cool-down: ${waitSec}s.`,
      );
      const choice = await select<"wait" | "already">({
        message: "What now?",
        choices: [
          {
            name: `Wait ${waitSec}s and send a new code`,
            value: "wait",
          },
          {
            name: "I already have the previous code — use it",
            value: "already",
          },
        ],
      });
      if (choice === "already") return;
      process.stdout.write(kleur.dim(`  · Waiting ${waitSec}s`));
      for (let i = 0; i < waitSec; i += 1) {
        await new Promise((r) => setTimeout(r, 1000));
        process.stdout.write(kleur.dim("."));
      }
      console.log();
      process.stdout.write(kleur.dim("  · Sending code… "));
      await sendOtp(email);
      console.log(kleur.dim("done."));
      return;
    }
    // Unreachable-server case: re-throw so the outer error handler shows
    // the actionable hint (from ApiError.hint).
    if (err instanceof ApiError && err.kind === "unreachable") throw err;
    throw new Error(msg);
  }
}
