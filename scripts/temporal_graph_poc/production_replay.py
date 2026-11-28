"""Read-only staged production smoke with distinct original sessions.

Backend credentials remain inside its existing container. This is an explicitly
scoped administrative experiment, not a new production API or an accuracy judge.
"""

import argparse
import hashlib
import inspect
import json
import os
import shlex
import subprocess
from datetime import datetime
from pathlib import Path
from uuid import UUID


def unique_sessions(hints):
    return list(dict.fromkeys(hint["session_id"] for hint in hints))[:3]


REMOTE = """import json,sys,time,hashlib
from pathlib import Path
from db.client import get_supabase
from services import agent_memory
payload=json.load(sys.stdin)
sb=get_supabase()
print(json.dumps(dict(type="start",questions_sha256=payload["questions_sha256"],implementation_sha256=hashlib.sha256(Path(agent_memory.__file__).read_bytes()).hexdigest(),strategy="journal_guided",deduplicate_sessions=True)),flush=True)
counts={"cases":0,"failures":0,"original_calls":0,"duplicates_prevented":0}
for case in payload["cases"]:
 started=time.perf_counter()
 common=dict(user_id=payload["user_id"],allowed=[payload["folder_id"]],query=case["question"],folder=payload["folder_id"],as_of=case["as_of"],tz="America/Sao_Paulo",strategy="journal_guided",evidence_mode="cached_preview",limit=8,order="relevance")
 row=dict(case_id=case["id"],status="ok",sessions=[])
 try:
  discovery=agent_memory.search_memory(sb,**common)
  row["discovery"]=discovery
  row["discovery_ms"]=(time.perf_counter()-started)*1000
 except Exception as exc:
  row.update(status="error",stage="discovery",error_type=type(exc).__name__,detail=getattr(exc,"detail",None))
 if row["status"]=="ok":
  hints=row["discovery"].get("journal_hints",[])
  selected=unique_sessions(hints)
  row["duplicate_calls_prevented"]=len(hints)-len(selected)
  counts["duplicates_prevented"]+=row["duplicate_calls_prevented"]
  for session_id in selected:
   begin=time.perf_counter()
   result=dict(session_id=session_id,status="ok")
   try:
    result["result"]=agent_memory.search_memory(sb,session=session_id,**common)
   except Exception as exc:
    result.update(status="error",error_type=type(exc).__name__,detail=getattr(exc,"detail",None))
    row.update(status="error",stage="selected_session_originals")
   result["latency_ms"]=(time.perf_counter()-begin)*1000
   row["sessions"].append(result)
   counts["original_calls"]+=1
 row["total_ms"]=(time.perf_counter()-started)*1000
 counts["cases"]+=1
 counts["failures"]+=row["status"]!="ok"
 print(json.dumps(row,default=str),flush=True)
print(json.dumps(dict(type="complete",**counts)),flush=True)
"""


def run(args):
    raw = args.questions.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.sha256:
        raise ValueError("Question manifest changed")
    cases = json.loads(raw)["cases"]
    if not 1 <= len(cases) <= 50 or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Invalid cases")
    for c in cases:
        if (
            datetime.fromisoformat(c["as_of"]).tzinfo is None
            or len(c["question"]) > 2000
        ):
            raise ValueError("Invalid cutoff or question")
    payload = {
        "user_id": str(UUID(args.user_id)),
        "folder_id": str(UUID(args.folder_id)),
        "cases": cases,
        "questions_sha256": args.sha256,
    }
    remote = inspect.getsource(unique_sessions) + "\n" + REMOTE
    with (
        os.fdopen(
            os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as out,
        os.fdopen(
            os.open(
                str(args.output) + ".errors.log",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            ),
            "w",
        ) as err,
    ):
        subprocess.run(
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=6",
                args.host,
                "docker exec -i kioku-backend python -c " + shlex.quote(remote),
            ],
            input=json.dumps(payload),
            text=True,
            stdout=out,
            stderr=err,
            check=True,
            timeout=600,
        )
    rows = [json.loads(l) for l in args.output.read_text().splitlines()]
    if rows[-1].get("type") != "complete" or rows[-1]["cases"] != len(cases):
        raise ValueError("Incomplete production smoke")
    print(json.dumps(rows[-1]))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["questions", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    for name in ["sha256", "user-id", "folder-id", "host"]:
        p.add_argument("--" + name, required=True)
    run(p.parse_args())
