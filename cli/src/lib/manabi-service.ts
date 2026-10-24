import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

type Run = (
  command: string,
  args: string[]
) => { status: number | null; stdout: string; stderr: string };
interface ServiceOptions {
  platform: string;
  home: string;
  root: string;
  executable: string;
  entry: string;
  config: string;
  uid?: number;
  run: Run;
  beforeStart: () => void;
}
const xml = (value: string) =>
  value.replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;" }[
        c
      ]!)
  );
const ps = (value: string) => `'${value.replace(/'/g, "''")}'`;
const unitArg = (value: string) =>
  `"${value
    .replace(/\\/g, "\\\\")
    .replace(/"/g, '\\"')
    .replace(/%/g, "%%")
    .replace(/\$/g, "$$")}"`;
function writeChanged(path: string, content: string): boolean {
  if (existsSync(path) && readFileSync(path, "utf8") === content) return false;
  writeFileSync(path, content, { mode: 0o600 });
  return true;
}

export function installManabiService(options: ServiceOptions): void {
  const { platform, home, root, executable, entry, config, run, beforeStart } =
    options;
  if ([executable, entry, config, root].some((value) => /[\r\n\0]/.test(value)))
    throw new Error("Invalid service path");
  const checked = (command: string, args: string[]) => {
    if (run(command, args).status !== 0)
      throw new Error(
        `Manabi startup failed (${command}). Check your user service manager, then re-run kioku init.`
      );
  };
  mkdirSync(root, { recursive: true, mode: 0o700 });
  if (platform === "darwin") {
    if (options.uid === undefined)
      throw new Error("Cannot determine macOS user service domain");
    const domain = `gui/${options.uid}`;
    const label = "com.kioku.manabi";
    const dir = join(home, "Library", "LaunchAgents");
    mkdirSync(dir, { recursive: true });
    const path = join(dir, `${label}.plist`);
    const content = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${label}</string>
<key>ProgramArguments</key><array>${[executable, entry, config]
      .map((arg) => `<string>${xml(arg)}</string>`)
      .join("")}</array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>10</integer>
<key>StandardOutPath</key><string>/dev/null</string>
<key>StandardErrorPath</key><string>/dev/null</string>
</dict></plist>\n`;
    const changed = writeChanged(path, content);
    const loaded =
      run("launchctl", ["print", `${domain}/${label}`]).status === 0;
    beforeStart();
    if (loaded && changed)
      checked("launchctl", ["bootout", `${domain}/${label}`]);
    checked("launchctl", ["enable", `${domain}/${label}`]);
    if (!loaded || changed) {
      // launchd can briefly retain an unloaded label; retry its transient I/O error.
      for (let attempt = 0; ; attempt++) {
        const result = run("launchctl", ["bootstrap", domain, path]);
        if (result.status === 0) break;
        if (result.status !== 5 || attempt === 4)
          throw new Error(
            "Manabi startup failed (launchctl). Re-run kioku init in a macOS login session."
          );
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 200);
      }
    } else checked("launchctl", ["kickstart", `${domain}/${label}`]);
  } else if (platform === "linux") {
    checked("systemctl", ["--user", "show-environment"]);
    const dir = join(home, ".config", "systemd", "user");
    mkdirSync(dir, { recursive: true });
    const changed = writeChanged(
      join(dir, "kioku-manabi.service"),
      `[Unit]
Description=Kioku Manabi connection
StartLimitIntervalSec=0
[Service]
Type=simple
ExecStart=${[executable, entry, config].map(unitArg).join(" ")}
Restart=always
RestartSec=10
StandardOutput=null
StandardError=null
[Install]
WantedBy=default.target
`
    );
    beforeStart();
    checked("systemctl", ["--user", "daemon-reload"]);
    checked("systemctl", ["--user", "enable", "--now", "kioku-manabi.service"]);
    if (changed)
      checked("systemctl", ["--user", "restart", "kioku-manabi.service"]);
  } else if (platform === "win32") {
    const actionArgs = `"${entry}" "${config}"`;
    const script = `$ErrorActionPreference='Stop'
$identity=[System.Security.Principal.WindowsIdentity]::GetCurrent()
$user=$identity.Name
$taskName='KiokuManabi-'+$identity.User.Value
$action=New-ScheduledTaskAction -Execute ${ps(executable)} -Argument ${ps(
      actionArgs
    )}
$trigger=New-ScheduledTaskTrigger -AtLogOn -User $user
$watchdog=New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$existing=Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and (($existing.Actions.Execute -ne ${ps(
      executable
    )}) -or ($existing.Actions.Arguments -ne ${ps(
      actionArgs
    )}))) { Stop-ScheduledTask -TaskName $taskName }
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($trigger,$watchdog) -Principal $principal -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
`;
    beforeStart();
    checked("powershell.exe", [
      "-NoProfile",
      "-NonInteractive",
      "-EncodedCommand",
      Buffer.from(script, "utf16le").toString("base64"),
    ]);
  } else
    throw new Error(`Manabi automatic startup is not supported on ${platform}`);
}
