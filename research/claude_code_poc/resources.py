"""Sample only POC descendants; record process metrics without command arguments."""

import json
import subprocess
import time
from pathlib import Path


def main():
    root = Path("/private/tmp/kioku-claude-poc-runtime")
    started = time.monotonic()
    while time.monotonic() - started < 10800:
        roots = set()
        for pidfile in root.glob("*.pid"):
            try:
                roots.add(int(pidfile.read_text()))
            except (ValueError, OSError):
                pass
        processes = []
        for line in subprocess.check_output(
            ["ps", "-axo", "pid=,ppid=,rss=,pcpu=,comm="], text=True
        ).splitlines():
            fields = line.split(None, 4)
            if len(fields) == 5:
                try:
                    processes.append(
                        {
                            "pid": int(fields[0]),
                            "ppid": int(fields[1]),
                            "rss_kib": int(fields[2]),
                            "cpu_lifetime_percent": float(fields[3]),
                            "executable": Path(fields[4]).name,
                        }
                    )
                except ValueError:
                    pass
        descendants = roots.copy()
        for _ in range(10):
            descendants.update(p["pid"] for p in processes if p["ppid"] in descendants)
        selected = [p for p in processes if p["pid"] in descendants]
        record = {
            "epoch": time.time(),
            "elapsed_s": time.monotonic() - started,
            "process_count": len(selected),
            "sum_process_rss_kib": sum(p["rss_kib"] for p in selected),
            "processes": selected,
        }
        with (root / "resources.jsonl").open("a") as output:
            output.write(json.dumps(record) + "\n")
        time.sleep(30)


if __name__ == "__main__":
    main()
