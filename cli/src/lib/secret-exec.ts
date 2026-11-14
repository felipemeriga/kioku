import { Transform, type TransformCallback, type Writable } from "node:stream";
import { StringDecoder } from "node:string_decoder";
import { spawn } from "node:child_process";

export interface ResolvedAccess {
  invocation_id: string;
  environment: Record<string, string>;
  clear_env: string[];
  credential_expires_at: string | null;
}
const dangerous = (name: string) =>
  /^(LD_|DYLD_|NODE_OPTIONS$|NODE_PATH$|BASH_ENV$|ENV$|SHELLOPTS$|BASHOPTS$|PS4$|PYTHONPATH$|PYTHONHOME$|PERL5OPT$|RUBYOPT$)/i.test(
    name,
  );
const validName = (name: string) => /^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(name);
export function buildSecretEnvironment(
  parent: NodeJS.ProcessEnv,
  values: Record<string, string>,
  clear: string[],
): NodeJS.ProcessEnv {
  if (
    !values ||
    Array.isArray(values) ||
    typeof values !== "object" ||
    Object.keys(values).length === 0 ||
    Object.keys(values).length > 32 ||
    !Array.isArray(clear) ||
    clear.length > 128
  )
    throw Error("Invalid credential mapping.");
  let size = 0;
  for (const [key, value] of Object.entries(values)) {
    if (
      !validName(key) ||
      dangerous(key) ||
      typeof value !== "string" ||
      !value ||
      value.includes("\0") ||
      Buffer.byteLength(value) > 65536
    )
      throw Error("Unsupported credential mapping.");
    size += Buffer.byteLength(value);
  }
  if (
    size > 262144 ||
    clear.some((k) => typeof k !== "string" || !validName(k))
  )
    throw Error("Credential mapping exceeds supported limits.");
  const env = { ...parent };
  for (const key of Object.keys(env))
    if (dangerous(key) || clear.includes(key)) delete env[key];
  for (const [key, value] of Object.entries(values)) env[key] = value;
  return env;
}

/** Bounded lookbehind keeps secrets split across data events out of forwarded output.
 * Defense in depth only: arbitrary transformed/exfiltrated values cannot be detected.
 */
export function createSecretRedactor(values: string[]): Transform {
  if (
    !values.length ||
    values.some(
      (v) => typeof v !== "string" || !v || Buffer.byteLength(v) > 65536,
    )
  )
    throw Error("Invalid redaction values.");
  const variants = new Set<string>();
  for (const value of values) {
    variants.add(value);
    variants.add(JSON.stringify(value).slice(1, -1));
    variants.add(encodeURIComponent(value));
    variants.add(
      encodeURIComponent(value).replace(/%[A-F0-9]{2}/g, (v) =>
        v.toLowerCase(),
      ),
    );
  }
  const patterns = [...variants].sort((a, b) => b.length - a.length);
  const max = patterns[0].length,
    decoder = new StringDecoder("utf8");
  let pending = "";
  function emit(stream: Transform, final: boolean) {
    let pos = 0,
      out = "";
    const limit = final
      ? pending.length
      : Math.max(0, pending.length - max + 1);
    while (pos < limit) {
      const found = patterns.find((p) => pending.startsWith(p, pos));
      if (found) {
        out += "[redacted]";
        pos += found.length;
      } else {
        out += pending[pos];
        pos++;
      }
    }
    pending = pending.slice(pos);
    if (out) stream.push(out);
  }
  return new Transform({
    transform(chunk: Buffer, _encoding: BufferEncoding, cb: TransformCallback) {
      pending += decoder.write(chunk);
      emit(this, false);
      cb();
    },
    flush(cb: TransformCallback) {
      pending += decoder.end();
      emit(this, true);
      cb();
    },
  });
}

export async function runSecretCommand(
  argv: string[],
  resolved: ResolvedAccess,
  outputs: { stdout: Writable; stderr: Writable } = {
    stdout: process.stdout,
    stderr: process.stderr,
  },
): Promise<number> {
  if (process.platform === "win32")
    throw Error("Secret execution currently supports macOS and Linux.");
  if (
    !argv.length ||
    argv.some((v) => typeof v !== "string" || v.includes("\0"))
  )
    throw Error("Provide a command after --.");
  const env = buildSecretEnvironment(
    process.env,
    resolved.environment,
    resolved.clear_env,
  );
  let duration = 3600000;
  if (resolved.credential_expires_at) {
    const expiry = Date.parse(resolved.credential_expires_at);
    if (!Number.isFinite(expiry) || expiry - Date.now() < 60000)
      throw Error("Credential expired or too close to expiry.");
    duration = Math.min(duration, expiry - Date.now() - 30000);
  }
  const values = Object.values(resolved.environment);
  const stdout = createSecretRedactor(values),
    stderr = createSecretRedactor(values);
  return new Promise((resolve, reject) => {
    const child = spawn(argv[0], argv.slice(1), {
      env,
      shell: false,
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stopping = false;
    let escalation: ReturnType<typeof setTimeout> | undefined;
    const kill = (signal: NodeJS.Signals) => {
      if (!child.pid) return;
      try {
        process.kill(-child.pid, signal);
      } catch {
        /* already exited */
      }
    };
    const stop = () => {
      if (stopping) return;
      stopping = true;
      kill("SIGTERM");
      escalation = setTimeout(() => kill("SIGKILL"), 3000);
      escalation.unref();
    };
    const timer = setTimeout(stop, duration);
    timer.unref();
    process.on("SIGINT", stop);
    process.on("SIGTERM", stop);
    const cleanup = () => {
      clearTimeout(timer);
      if (escalation) clearTimeout(escalation);
      process.off("SIGINT", stop);
      process.off("SIGTERM", stop);
    };
    stdout.pipe(outputs.stdout, { end: false });
    stderr.pipe(outputs.stderr, { end: false });
    child.stdout.pipe(stdout);
    child.stderr.pipe(stderr);
    child.once("error", () => {
      cleanup();
      reject(
        Error(
          "Could not start the command. Check its executable and permissions.",
        ),
      );
    });
    child.once("close", (code, signal) => {
      cleanup();
      resolve(
        code ?? (signal === "SIGINT" ? 130 : signal === "SIGTERM" ? 143 : 1),
      );
    });
  });
}
