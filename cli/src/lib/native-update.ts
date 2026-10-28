import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

const releaseBase = "https://github.com/felipemeriga/kioku/releases/download";

export async function installNativeUpdate(version: string): Promise<void> {
  if (!/^\d+\.\d+\.\d+$/.test(version))
    throw new Error("Invalid CLI release version");
  const script = process.platform === "win32" ? "install.ps1" : "install.sh";
  const base = `${releaseBase}/cli-v${version}`;
  const signal = AbortSignal.timeout(30_000);
  const [installerResponse, sumsResponse] = await Promise.all([
    fetch(`${base}/${script}`, { signal }),
    fetch(`${base}/SHA256SUMS`, { signal })
  ]);
  if (!installerResponse.ok || !sumsResponse.ok) {
    throw new Error("Could not download the Kioku updater");
  }
  const installer = Buffer.from(await installerResponse.arrayBuffer());
  const sums = await sumsResponse.text();
  const hashes = sums
    .split(/\r?\n/)
    .filter((line) => line.endsWith(`  ${script}`));
  const actual = createHash("sha256").update(installer).digest("hex");
  if (hashes.length !== 1 || hashes[0]?.split("  ")[0] !== actual) {
    throw new Error("Kioku updater checksum verification failed");
  }

  const dir = mkdtempSync(join(tmpdir(), "kioku-update-"));
  const path = join(dir, script);
  writeFileSync(path, installer);
  const env = {
    ...process.env,
    KIOKU_VERSION: version,
    KIOKU_INSTALL_DIR: dirname(process.execPath)
  };
  if (process.platform === "win32") {
    // Windows cannot replace a running .exe. Let a detached PowerShell wait
    // for this process to exit, then run the verified installer.
    const escaped = path.replace(/'/g, "''");
    const command = `while (Get-Process -Id ${process.pid} -ErrorAction SilentlyContinue) { Start-Sleep -Milliseconds 200 }; & '${escaped}'; Remove-Item '${escaped}' -Force; Remove-Item '${dir.replace(/'/g, "''")}' -Force`;
    await new Promise<void>((resolve, reject) => {
      const child = spawn(
        "powershell.exe",
        [
          "-NoProfile",
          "-ExecutionPolicy",
          "Bypass",
          "-EncodedCommand",
          Buffer.from(command, "utf16le").toString("base64")
        ],
        { detached: true, stdio: "ignore", env }
      );
      child.once("error", reject);
      child.once("spawn", () => {
        child.unref();
        resolve();
      });
    });
    return;
  }
  try {
    chmodSync(path, 0o700);
    const result = spawnSync("sh", [path], { stdio: "inherit", env });
    if (result.error || result.status !== 0) {
      throw (
        result.error ??
        new Error(`Kioku updater exited with status ${result.status}`)
      );
    }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
