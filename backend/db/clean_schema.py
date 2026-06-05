"""One-shot cleaner for the pg_dump output produced by `supabase db dump`.

Strips owner / grant / revoke / default-privilege noise (all single-line in this
dump) and prepends the CREATE EXTENSION statements that pg_dump omits.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SRC = Path("backend/db/schema.sql")

HEADER = """\
-- backend/db/schema.sql
-- Canonical Postgres schema for agentic-rag.
-- Generated from `supabase db dump --schema public` against prod, then cleaned:
--   - Owner / grant / revoke / default-privilege statements stripped
--   - CREATE EXTENSION statements prepended (Supabase manages these separately)
-- Applied by the eval harness against a fresh `supabase start` instance.
-- When prod schema changes, re-dump and re-clean.

CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

"""

STRIP_LINE_PATTERNS = [
    re.compile(r"^\s*ALTER\s+(TABLE|FUNCTION|SCHEMA|TYPE|SEQUENCE|VIEW)\s+.*OWNER\s+TO\s+", re.I),
    re.compile(r"^\s*ALTER\s+DEFAULT\s+PRIVILEGES\s+", re.I),
    re.compile(r"^\s*GRANT\s+", re.I),
    re.compile(r"^\s*REVOKE\s+", re.I),
]


def main() -> int:
    if not SRC.exists():
        print(f"missing {SRC}", file=sys.stderr)
        return 1

    kept = []
    for line in SRC.read_text().splitlines():
        if any(p.match(line) for p in STRIP_LINE_PATTERNS):
            continue
        kept.append(line)

    body = "\n".join(kept)
    body = re.sub(r"\n{3,}", "\n\n", body)
    SRC.write_text(HEADER + body.lstrip("\n") + "\n")
    print(f"wrote cleaned {SRC} ({len(kept)} lines after strip)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
