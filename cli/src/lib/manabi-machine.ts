import { hostname, platform, arch } from "node:os";
import { isIP } from "node:net";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
export interface MachineInfo {
  name: string;
  os_name: string;
  os_id: string;
  architecture: string;
}
export function machineInfo(
  options: {
    platform?: string;
    hostname?: string;
    architecture?: string;
    run?: (command: string, args: string[]) => string;
    osRelease?: string;
  } = {}
): MachineInfo {
  const os = options.platform ?? platform();
  const run =
    options.run ??
    ((command, args) =>
      spawnSync(command, args, {
        encoding: "utf8",
        timeout: 2000,
        windowsHide: true,
      }).stdout?.trim() ?? "");
  let name = "";
  if (os === "darwin") name = run("scutil", ["--get", "ComputerName"]);
  else if (os === "linux") name = run("hostnamectl", ["--pretty"]);
  else if (os === "win32") name = process.env.COMPUTERNAME ?? "";
  const fallback = options.hostname ?? hostname();
  if (!name.trim() || isIP(name.trim())) name = isIP(fallback) ? "" : fallback;
  name = [...name]
    .filter((char) => char.charCodeAt(0) >= 32 && char.charCodeAt(0) !== 127)
    .join("")
    .trim()
    .slice(0, 120);
  let release = options.osRelease ?? "";
  if (os === "linux" && options.osRelease === undefined) {
    try {
      release = readFileSync("/etc/os-release", "utf8");
    } catch {
      /* Generic Linux is accurate without distro metadata. */
    }
  }
  const ubuntu = /^ID=["']?ubuntu["']?$/m.test(release);
  const os_name =
    os === "darwin"
      ? "macOS"
      : os === "win32"
      ? "Windows"
      : ubuntu
      ? "Ubuntu"
      : os === "linux"
      ? "Linux"
      : os;
  return {
    name: name || `${os_name} computer`,
    os_name,
    os_id:
      os === "darwin"
        ? "macos"
        : os === "win32"
        ? "windows"
        : ubuntu
        ? "ubuntu"
        : os,
    architecture: options.architecture ?? arch(),
  };
}
