# Manual agent-memory replay

Run from an authorized repository with a current Kioku CLI and an existing MCP binding. Keep the real manifest and receipts outside the repository. The example is synthetic and cannot exercise a real archive as written.

1. Put real questions and explicit folder and offset-aware `as_of` filters in a private copy of [example.json](example.json). Optional filters are `from_date`, `through_date`, `timezone`, and `session`. Use synthetic case labels in the manifest.
2. Freeze the manifest and record its SHA-256 independently (`shasum -a 256 /private/path/queries.json`). Choose an offset-aware cutoff ceiling before the activity you want to exclude. Every question must be at or below that ceiling.
3. Run manually with a fresh output filename.

```bash
python3 /path/to/kioku/scripts/memory_eval/live_replay.py \
  --queries /private/path/queries.json --sha256 "$SEALED_MANIFEST_SHA256" \
  --cutoff-ceiling 2026-01-15T18:00:00Z \
  --output /private/path/replay.jsonl \
  --strategy journal-guided --evidence-mode cached-preview
```

Use `--strategy original --evidence-mode hydrate` for a baseline. Use the same manifest and cutoff for the comparison. Each trial searches at most 10 matches and opens at most two distinct signed references. Journal-guided discovery can return hints without searching originals. A separate, explicitly scoped replay can pin an original session for follow-up.

The runner opens only the input manifest and creates its receipt exclusively with mode `0600`. The JSONL receipt can contain private source excerpts and signed references. Protect it accordingly. The console prints counts, case labels, and search timings. Check for the terminal completion record after interruptions.

Journal hints, original excerpts, deferred locators, and successful signed reads are separate observations. They measure whether the retrieval stages responded and expose no answer accuracy score. The runner loads no answer annotations.

Run the mocks-only tests locally with `python3 -m unittest discover -s scripts/memory_eval -p 'test_*.py'`. They make no live requests.

Each trial also checks original match and signed-read recording times, and journal capture and sync times, against the query's `as_of`. The counts are per timestamp. `cutoff_violations` counts times after the cutoff. `cutoff_unverifiable` counts missing, invalid, or offset-free times. The runner retains the receipt in both cases. These checks use metadata and do not establish that a journal report is original evidence.
