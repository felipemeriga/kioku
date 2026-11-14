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
const processControl = (name: string) =>
  /^(PATH|HOME|USERPROFILE|COMSPEC|SYSTEMROOT|PATHEXT|IFS|CDPATH|ZDOTDIR|PYTHONSTARTUP)$/i.test(
    name,
  );
const awsSelectors = new Set([
  "AWS_PROFILE",
  "AWS_DEFAULT_PROFILE",
  "AWS_CONFIG_FILE",
  "AWS_SHARED_CREDENTIALS_FILE",
  "AWS_WEB_IDENTITY_TOKEN_FILE",
  "AWS_ROLE_ARN",
  "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
  "AWS_CONTAINER_CREDENTIALS_FULL_URI",
  "AWS_CONTAINER_AUTHORIZATION_TOKEN",
  "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
  "AWS_EC2_METADATA_SERVICE_ENDPOINT",
  "AWS_EC2_METADATA_DISABLED",
]);
const mongoAliases = [
  "MONGO_URI",
  "MONGODB_URI",
  "MONGODB_URL",
  "MONGO_URL",
  "MONGO_DB_URL",
];
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
      processControl(key) ||
      awsSelectors.has(key) ||
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
    clear.some(
      (k) => typeof k !== "string" || !validName(k) || processControl(k),
    )
  )
    throw Error("Credential mapping exceeds supported limits.");
  const env = { ...parent };
  const aws = Object.keys(values).some((k) => k.startsWith("AWS_"));
  if (aws) {
    if (!values.AWS_ACCESS_KEY_ID || !values.AWS_SECRET_ACCESS_KEY)
      throw Error("AWS execution requires a complete credential bundle.");
    for (const key of [
      ...awsSelectors,
      "AWS_ACCESS_KEY_ID",
      "AWS_SECRET_ACCESS_KEY",
      "AWS_SESSION_TOKEN",
      "AWS_SECURITY_TOKEN",
    ])
      delete env[key];
    env.AWS_CONFIG_FILE = "/dev/null";
    env.AWS_SHARED_CREDENTIALS_FILE = "/dev/null";
    env.AWS_EC2_METADATA_DISABLED = "true";
  }
  if (mongoAliases.some((k) => k in values))
    for (const key of mongoAliases) delete env[key];
  for (const key of Object.keys(env))
    if (dangerous(key) || clear.includes(key)) delete env[key];
  for (const [key, value] of Object.entries(values)) env[key] = value;
  if (aws) {
    env.AWS_CONFIG_FILE = "/dev/null";
    env.AWS_SHARED_CREDENTIALS_FILE = "/dev/null";
    env.AWS_EC2_METADATA_DISABLED = "true";
  }
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
        const point = pending.codePointAt(pos)!;
        out += String.fromCodePoint(point);
        pos += point > 0xffff ? 2 : 1;
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
    let stopCode: number | undefined;
    let forceKilled = false;
    let closedResult: number | undefined;
    let escalation: ReturnType<typeof setTimeout> | undefined;
    const kill = (signal: NodeJS.Signals) => {
      if (!child.pid) return;
      try {
        process.kill(-child.pid, signal);
      } catch {
        /* already exited */
      }
    };
    const stop = (signal: NodeJS.Signals, exitCode: number) => {
      if (stopping) return;
      stopping = true;
      stopCode = exitCode;
      kill(signal);
      escalation = setTimeout(() => {
        kill("SIGKILL");
        forceKilled = true;
        if (closedResult !== undefined) {
          cleanup();
          resolve(closedResult);
        }
      }, 3000);
      // Keep escalation alive even if the group leader exits before descendants.
    };
    const interrupt = () => stop("SIGINT", 130);
    const terminate = () => stop("SIGTERM", 143);
    const timer = setTimeout(() => stop("SIGTERM", 124), duration);
    timer.unref();
    process.on("SIGINT", interrupt);
    process.on("SIGTERM", terminate);
    const cleanup = () => {
      clearTimeout(timer);
      if (escalation) clearTimeout(escalation);
      process.off("SIGINT", interrupt);
      process.off("SIGTERM", terminate);
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
      closedResult =
        stopCode ??
        code ??
        (signal === "SIGINT" ? 130 : signal === "SIGTERM" ? 143 : 1);
      if (stopping && !forceKilled) return;
      cleanup();
      resolve(closedResult);
    });
  });
}
