"""Create a private, frozen journal-vector baseline using existing Voyage access.

The authorized backend keeps credentials inside its environment. This performs no
Supabase or production index writes, and does not embed original transcripts.
"""

import argparse
import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
from pathlib import Path

REMOTE = """import sys,json,time,hashlib,importlib.metadata
from services.embeddings import get_voyage_client
payload=json.load(sys.stdin)
client=get_voyage_client()
print(json.dumps(dict(type="start",model="voyage-3",dimension=1024,voyageai_version=importlib.metadata.version("voyageai"),payload_sha256=payload["payload_sha256"])),flush=True)
for kind in ["documents","queries"]:
 rows=payload[kind]
 for start in range(0,len(rows),64):
  batch=rows[start:start+64]
  before=time.perf_counter()
  result=client.embed([r["text"] for r in batch],model="voyage-3",input_type="document" if kind=="documents" else "query")
  if len(result.embeddings)!=len(batch):raise ValueError("Incomplete embedding batch")
  for source,vector in zip(batch,result.embeddings,strict=True):
   print(json.dumps(dict(type="vector",kind=kind,id=source["id"],text_sha256=hashlib.sha256(source["text"].encode()).hexdigest(),vector=vector)),flush=True)
  print(json.dumps(dict(type="batch",kind=kind,start=start,count=len(batch),latency_ms=(time.perf_counter()-before)*1000,total_tokens=getattr(result,"total_tokens",None))),flush=True)
print(json.dumps(dict(type="complete",documents=len(payload["documents"]),queries=len(payload["queries"]),payload_sha256=payload["payload_sha256"])),flush=True)
"""


def run(args):
    db = sqlite3.connect(f"file:{args.corpus}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    documents = [
        {"id": r["id"], "text": r["title"] + "\n\n" + r["body"]}
        for r in db.execute("SELECT id,title,body FROM journals ORDER BY id")
    ]
    cases = [
        c for path in args.questions for c in json.loads(path.read_text())["cases"]
    ]
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate question ids")
    payload = {
        "documents": documents,
        "queries": [{"id": c["id"], "text": c["question"]} for c in cases],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    payload["payload_sha256"] = digest
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
                "docker exec -i kioku-backend python -c " + shlex.quote(REMOTE),
            ],
            input=json.dumps(payload),
            text=True,
            stdout=out,
            stderr=err,
            check=True,
            timeout=300,
        )
    rows = [json.loads(l) for l in args.output.read_text().splitlines()]
    if (
        rows[-1].get("type") != "complete"
        or rows[-1]["payload_sha256"] != digest
        or rows[-1]["documents"] != len(documents)
        or rows[-1]["queries"] != len(cases)
    ):
        raise ValueError("Incomplete vector export")
    print(
        json.dumps(
            {**rows[-1], "scope": "private journal-only baseline; production unchanged"}
        )
    )
    db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--questions", type=Path, action="append", required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--output", type=Path, required=True)
    run(p.parse_args())
