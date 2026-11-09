"""Export one explicitly scoped, immutable originals snapshot through existing SSH auth."""

import argparse
import json
import os
import subprocess
from pathlib import Path

REMOTE = """import json
from db.client import get_supabase
from services.agent_evidence import EvidenceStore
sb=get_supabase()
folder=FOLDER
sessions=sb.table("agent_evidence_sessions").select("*").eq("folder_id",folder).is_("deleted_at","null").execute().data
for s in sessions:
 store=EvidenceStore(sb,s["user_id"],folder)
 print(json.dumps({"kind":"session","session":{k:s[k] for k in ["id","agent","native_session_id","manifest_revision","indexed_revision","event_count","first_event_at","last_event_at"]}}),flush=True)
 events=[]
 for start in range(0,s["event_count"]+1000,500):
  page=sb.table("agent_evidence_events").select("event_id,object_id,byte_offset,byte_length,event_at,role,event_type,record_sequence,call_id").eq("user_id",s["user_id"]).eq("folder_id",folder).eq("session_id",s["id"]).eq("inherited",False).eq("displayable",True).order("position").range(start,start+499).execute().data
  events.extend(page)
  if len(page)<500:break
 cached={}
 for e in events:
  oid=e["object_id"]
  if oid not in cached:cached[oid]=store.download(store.object(s["id"],oid))
  b=cached[oid][e["byte_offset"]:e["byte_offset"]+e["byte_length"]]
  print(json.dumps({"kind":"record","session_id":s["id"],**e,"original":json.loads(b)}),flush=True)
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import uuid

    uuid.UUID(args.folder)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "meriga-server",
                "docker",
                "exec",
                "-i",
                "kioku-backend",
                "python",
                "-",
            ],
            input=REMOTE.replace("folder=FOLDER", "folder=" + repr(args.folder)),
            text=True,
            stdout=output,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode:
        raise RuntimeError("Snapshot export failed; incomplete file retained privately")
    rows = [json.loads(line) for line in args.output.read_text().splitlines()]
    print(
        json.dumps(
            {
                "sessions": sum(r["kind"] == "session" for r in rows),
                "records": sum(r["kind"] == "record" for r in rows),
                "bytes": args.output.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    main()
