"""Copy an explicitly scoped, frozen object inventory through an existing SSH host.

The production process only downloads existing Storage objects. Service credentials
stay in its environment; corpus bytes go directly to a private local tar archive.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from pathlib import Path

REMOTE = r"""
import concurrent.futures, hashlib, io, json, sys, tarfile
from db.client import get_supabase_thread_safe
from services.agent_evidence import decode_stored_object

request = json.load(sys.stdin)
objects = request["objects"]
assert objects and len(objects) <= 20000
assert all(o["user_id"] == request["user_id"] and
           o["folder_id"] == request["folder_id"] and
           o["committed_revision"] is not None and
           o["kind"] in {"segment","attachment"} for o in objects)

def fetch(obj):
    try:
        data = get_supabase_thread_safe().storage.from_("agent-evidence").download(obj["storage_path"])
        raw = decode_stored_object(data, obj)
        if raw is None:
            return obj, None, "integrity_failure"
        return obj, raw, None
    except Exception as exc:
        return obj, None, type(exc).__name__

receipt = {"requested": len(objects), "verified": 0, "bytes": 0, "failures": []}
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        # Bounded batches avoid retaining a whole corpus of completed futures.
        for start in range(0, len(objects), 16):
            for obj, raw, error in pool.map(fetch, objects[start:start+16]):
                if error:
                    receipt["failures"].append({"sha256": obj["sha256"], "error": error})
                    continue
                entry = tarfile.TarInfo(("objects/" + obj["sha256"] + ".jsonl") if obj["kind"] == "segment" else ("attachments/" + obj["sha256"] + ".bin"))
                entry.size, entry.mode = len(raw), 0o600
                archive.addfile(entry, io.BytesIO(raw))
                receipt["verified"] += 1
                receipt["bytes"] += len(raw)
            print(json.dumps({"processed": min(start+16,len(objects)),
                              "verified": receipt["verified"]}), file=sys.stderr, flush=True)
    data = json.dumps(receipt, sort_keys=True).encode()
    entry = tarfile.TarInfo("receipt.json")
    entry.size, entry.mode = len(data), 0o600
    archive.addfile(entry, io.BytesIO(data))
if receipt["failures"]:
    sys.exit(2)
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objects", type=Path, required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--folder-id", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--container", default="kioku-backend")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--include-attachments", action="store_true")
    args = parser.parse_args()
    objects = json.loads(args.objects.read_text())
    if not all(
        obj["user_id"] == args.user_id and obj["folder_id"] == args.folder_id
        for obj in objects
    ):
        raise ValueError("Inventory exceeds explicitly authorized scope")
    objects = [
        obj
        for obj in objects
        if obj["kind"]
        in ({"segment", "attachment"} if args.include_attachments else {"segment"})
        and obj["committed_revision"] is not None
    ]
    request = {"user_id": args.user_id, "folder_id": args.folder_id, "objects": objects}
    command = shlex.join(
        ["docker", "exec", "-i", args.container, "python", "-c", REMOTE]
    )
    with os.fdopen(
        os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
    ) as out:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=6",
                args.host,
                command,
            ],
            input=json.dumps(request).encode(),
            stdout=out,
            check=False,
            timeout=3600,
        )
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
