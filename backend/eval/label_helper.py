"""Print stable chunk IDs alongside content snippets to make golden-set labeling tractable.

Usage:
    uv run python -m eval.label_helper

Reads fixture corpus from backend/tests/fixtures/corpus/, runs the real
chunker + parser (no DB writes), and prints one line per chunk:

    sha256:abc123...:chunk_0 | "First 180 chars of the chunk content..."

Copy the relevant chunk IDs into backend/tests/fixtures/golden_set.yaml.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from services.chunker import chunk_text
from services.parser import parse_document

CORPUS_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "corpus"


def main() -> int:
    if not CORPUS_DIR.exists():
        print(f"Corpus dir not found: {CORPUS_DIR}", file=sys.stderr)
        return 1

    files = sorted(p for p in CORPUS_DIR.iterdir() if p.is_file())
    for path in files:
        raw = path.read_bytes()
        content_hash = hashlib.sha256(raw).hexdigest()

        try:
            text = parse_document(raw, path.name)
        except Exception as exc:
            print(f"# parse failed for {path.name}: {exc}", file=sys.stderr)
            continue

        chunks = chunk_text(text)
        print(f"\n# === {path.name} ({len(chunks)} chunks, hash={content_hash[:12]}…) ===")
        for idx, chunk in enumerate(chunks):
            snippet = chunk[:180].replace("\n", " ")
            print(f"sha256:{content_hash}:chunk_{idx}  |  {snippet}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
