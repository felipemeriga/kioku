import {
  constants,
  chmodSync,
  closeSync,
  fstatSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import { parse as parseToml, stringify as stringifyToml } from "smol-toml";
export type Delivery =
  | { kind: "env"; environment: Record<string, string> }
  | {
      kind: "argv";
      arguments: Array<{ kind: "literal" | "secret"; value: string }>;
    }
  | {
      kind: "file";
      format: "json" | "yaml" | "toml";
      source_template: string;
      patches: Array<{ path: string[]; value: string }>;
      destination: { kind: "env" | "arg"; name: string };
      environment?: Record<string, string>;
    }
  | {
      kind: "ssh";
      host: string;
      user: string;
      port: number;
      host_key: string;
      private_key: string;
      passphrase?: string;
    };
const invalid = () => Error("Invalid or unsupported secret delivery.");
const text = (v: unknown, max = 65536): v is string =>
  typeof v === "string" &&
  v.length > 0 &&
  !v.includes("\0") &&
  Buffer.byteLength(v) <= max;
const safeSegment = (v: string) =>
  typeof v === "string" &&
  v.length <= 256 &&
  !["__proto__", "constructor", "prototype"].includes(v);
const base = () => join(tmpdir(), `kioku-secret-${process.getuid!()}`);
function ensureBase() {
  try {
    mkdirSync(base(), { mode: 0o700 });
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
  }
  const s = lstatSync(base());
  if (
    !s.isDirectory() ||
    s.isSymbolicLink() ||
    s.uid !== process.getuid!() ||
    (s.mode & 0o077) !== 0
  )
    throw invalid();
}
/** Hard kills may leave artifacts; delete only owned private expired invocation directories. */
export function cleanupStaleSecretFiles(now = Date.now()) {
  ensureBase();
  for (const name of readdirSync(base())) {
    if (!/^invoke-[A-Za-z0-9]{6}$/.test(name)) continue;
    const dir = join(base(), name);
    let s: ReturnType<typeof lstatSync>;
    try {
      s = lstatSync(dir);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") continue;
      throw error;
    }
    if (
      !s.isDirectory() ||
      s.isSymbolicLink() ||
      s.uid !== process.getuid!() ||
      (s.mode & 0o077) !== 0
    )
      continue;
    let fd: number | undefined;
    try {
      fd = openSync(
        join(dir, "expiry.json"),
        constants.O_RDONLY | constants.O_NOFOLLOW
      );
      const st = fstatSync(fd);
      if (
        !st.isFile() ||
        st.uid !== process.getuid!() ||
        st.size > 1024 ||
        (st.mode & 0o077) !== 0
      )
        continue;
      const m = JSON.parse(readFileSync(fd, "utf8"));
      if (m.version === 1 && Number.isFinite(m.expires) && m.expires < now)
        rmSync(dir, { recursive: true, force: true });
    } catch {
      /* Unrecognized artifacts are not ours. */
    } finally {
      if (fd !== undefined) closeSync(fd);
    }
  }
}
export function renderSecretConfig(
  format: string,
  template: string,
  patches: Array<{ path: string[]; value: string }>
) {
  if (
    !text(template, 262144) ||
    !Array.isArray(patches) ||
    !patches.length ||
    patches.length > 32
  )
    throw invalid();
  try {
    const data: any =
      format === "json"
        ? JSON.parse(template)
        : format === "yaml"
        ? parseYaml(template, { maxAliasCount: 0, uniqueKeys: true })
        : format === "toml"
        ? parseToml(template)
        : null;
    if (!data || typeof data !== "object" || Array.isArray(data))
      throw invalid();
    for (const p of patches) {
      if (
        !Array.isArray(p.path) ||
        !p.path.length ||
        p.path.length > 16 ||
        !p.path.every(safeSegment) ||
        !text(p.value)
      )
        throw invalid();
      let obj = data;
      for (const key of p.path.slice(0, -1)) {
        if (!obj || typeof obj !== "object" || !Object.hasOwn(obj, key))
          throw invalid();
        obj = obj[key];
      }
      const key = p.path.at(-1)!;
      if (!obj || typeof obj !== "object") throw invalid();
      obj[key] = p.value;
    }
    const result =
      format === "json"
        ? JSON.stringify(data, null, 2)
        : format === "yaml"
        ? stringifyYaml(data)
        : stringifyToml(data);
    if (Buffer.byteLength(result) > 524288) throw invalid();
    return result;
  } catch {
    throw invalid();
  }
}
/** AWS uses INI, whose parser does not unquote TOML string syntax. */
export function renderAwsCredentialsFile(template: string): string {
  const config = parseToml(template) as Record<string, unknown>;
  const profile = config.default;
  if (
    Object.keys(config).length !== 1 ||
    !profile ||
    typeof profile !== "object" ||
    Array.isArray(profile)
  )
    throw invalid();
  const entries = Object.entries(profile);
  if (
    !Object.hasOwn(profile, "aws_access_key_id") ||
    !Object.hasOwn(profile, "aws_secret_access_key") ||
    entries.some(
      ([key, value]) =>
        ![
          "aws_access_key_id",
          "aws_secret_access_key",
          "aws_session_token",
        ].includes(key) ||
        typeof value !== "string" ||
        !value ||
        /[\x00-\x20\x7f]/.test(value)
    )
  )
    throw invalid();
  return (
    "[default]\n" +
    entries.map(([key, value]) => `${key} = ${value}\n`).join("")
  );
}

export function prepareSecretDeliveries(
  deliveries: Delivery[],
  allowRaw = false
) {
  if (
    process.platform === "win32" ||
    !Array.isArray(deliveries) ||
    !deliveries.length ||
    deliveries.length > 8
  )
    throw invalid();
  cleanupStaleSecretFiles();
  const dir = mkdtempSync(join(base(), "invoke-"));
  chmodSync(dir, 0o700);
  const cleanup = () => rmSync(dir, { recursive: true, force: true });
  writeFileSync(
    join(dir, "expiry.json"),
    JSON.stringify({ version: 1, expires: Date.now() + 7200000 }),
    { mode: 0o600, flag: "wx" }
  );
  const environment: Record<string, string> = {},
    arguments_: string[] = [],
    secrets: string[] = [];
  let ssh: string[] | undefined;
  const trustedEnvironment: Record<string, string> = {};
  const clearEnvironment: string[] = [];
  const put = (name: string, value: string) => {
    if (
      !/^[A-Za-z_][A-Za-z0-9_]{0,127}$/.test(name) ||
      Object.hasOwn(environment, name)
    )
      throw invalid();
    environment[name] = value;
  };
  const file = (name: string, value: string) => {
    const p = join(dir, name);
    writeFileSync(p, value, { mode: 0o600, flag: "wx" });
    return p;
  };
  try {
    deliveries.forEach((d, i) => {
      if (d.kind === "env") {
        if (!d.environment || Object.keys(d.environment).length > 32)
          throw invalid();
        for (const [name, value] of Object.entries(d.environment)) {
          if (!text(value)) throw invalid();
          put(name, value);
          secrets.push(value);
        }
      } else if (d.kind === "argv") {
        if (!Array.isArray(d.arguments) || d.arguments.length > 64)
          throw invalid();
        for (const a of d.arguments) {
          if (
            !text(a.value) ||
            !["literal", "secret"].includes(a.kind) ||
            (a.kind === "secret" && !allowRaw)
          )
            throw invalid();
          arguments_.push(a.value);
          if (a.kind === "secret") secrets.push(a.value);
        }
      } else if (d.kind === "file") {
        const rendered = renderSecretConfig(
            d.format,
            d.source_template,
            d.patches
          ),
          path = file(
            `config-${i}.${d.format}`,
            d.destination.kind === "env" &&
              d.destination.name === "AWS_SHARED_CREDENTIALS_FILE"
              ? renderAwsCredentialsFile(rendered)
              : rendered
          );
        secrets.push(...d.patches.map((p) => p.value));
        if (
          d.destination.kind === "env" &&
          d.destination.name === "AWS_SHARED_CREDENTIALS_FILE"
        ) {
          const config = parseToml(rendered) as Record<string, unknown>;
          const profiles = Object.values(config);
          if (
            d.format !== "toml" ||
            profiles.length !== 1 ||
            !profiles[0] ||
            typeof profiles[0] !== "object" ||
            !(profiles[0] as Record<string, unknown>).aws_access_key_id ||
            !(profiles[0] as Record<string, unknown>).aws_secret_access_key
          )
            throw invalid();
          const profile = profiles[0] as Record<string, unknown>;
          if (
            Object.keys(config)[0] !== "default" ||
            Object.entries(profile).some(
              ([key, value]) =>
                ![
                  "aws_access_key_id",
                  "aws_secret_access_key",
                  "aws_session_token",
                ].includes(key) ||
                typeof value !== "string" ||
                !value ||
                /[\x00-\x20\x7f]/.test(value)
            )
          )
            throw invalid();
          for (const key of Object.keys(process.env))
            if (key.startsWith("AWS_")) clearEnvironment.push(key);
          trustedEnvironment.AWS_SHARED_CREDENTIALS_FILE = path;
          trustedEnvironment.AWS_CONFIG_FILE = "/dev/null";
          trustedEnvironment.AWS_EC2_METADATA_DISABLED = "true";
          if (d.environment)
            for (const [key, value] of Object.entries(d.environment)) {
              if (
                !["AWS_REGION", "AWS_DEFAULT_REGION"].includes(key) ||
                !text(value, 128)
              )
                throw invalid();
              trustedEnvironment[key] = value;
            }
        } else if (d.destination.kind === "env") put(d.destination.name, path);
        else if (
          d.destination.kind === "arg" &&
          /^--?[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(d.destination.name)
        )
          arguments_.push(d.destination.name, path);
        else throw invalid();
      } else if (d.kind === "ssh") {
        if (
          ssh ||
          !/^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$/.test(d.host) ||
          !/^[A-Za-z_][A-Za-z0-9_.-]{0,63}$/.test(d.user) ||
          !Number.isInteger(d.port) ||
          d.port < 1 ||
          d.port > 65535 ||
          !/^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)) [A-Za-z0-9+/]+={0,3}$/.test(
            d.host_key
          ) ||
          !text(d.private_key) ||
          (d.passphrase !== undefined && !text(d.passphrase))
        )
          throw invalid();
        const identity = file("identity", d.private_key),
          known = file(
            "known_hosts",
            `[${d.host}]:${d.port} ${d.host_key}\n${d.host} ${d.host_key}\n`
          );
        try {
          execFileSync("/usr/bin/ssh-keygen", ["-l", "-f", known], {
            stdio: "ignore",
            timeout: 3000,
          });
        } catch {
          throw invalid();
        }
        clearEnvironment.push(
          "SSH_AUTH_SOCK",
          "SSH_ASKPASS",
          "SSH_ASKPASS_REQUIRE",
          "DISPLAY"
        );
        secrets.push(d.private_key);
        if (d.passphrase) {
          const pass = file("passphrase", d.passphrase),
            helper = file(
              "askpass",
              `#!/bin/sh\nexec /bin/cat '${pass.replace(/'/g, "'\"'\"'")}'\n`
            );
          chmodSync(helper, 0o700);
          put("SSH_ASKPASS", helper);
          put("SSH_ASKPASS_REQUIRE", "force");
          put("DISPLAY", "kioku:0");
          secrets.push(d.passphrase);
        }
        ssh = [
          "/usr/bin/ssh",
          "-F",
          "/dev/null",
          "-o",
          "StrictHostKeyChecking=yes",
          "-o",
          `UserKnownHostsFile=${known}`,
          "-o",
          "GlobalKnownHostsFile=/dev/null",
          "-o",
          "IdentitiesOnly=yes",
          "-o",
          "IdentityAgent=none",
          "-o",
          "PasswordAuthentication=no",
          "-o",
          "KbdInteractiveAuthentication=no",
          "-o",
          "NumberOfPasswordPrompts=1",
          "-o",
          "ConnectTimeout=15",
          "-i",
          identity,
          "-p",
          String(d.port),
          `${d.user}@${d.host}`,
        ];
      } else throw invalid();
    });
    if (
      trustedEnvironment.AWS_SHARED_CREDENTIALS_FILE &&
      Object.keys(environment).some((key) => key.startsWith("AWS_"))
    )
      throw invalid();
    return {
      environment,
      arguments: arguments_,
      secrets,
      ssh,
      cleanup,
      directory: dir,
      trustedEnvironment,
      clearEnvironment,
    };
  } catch {
    cleanup();
    throw invalid();
  }
}
