# c360 temporal graph experiment

This is a manual, isolated experiment. It does not change Kioku retrieval, register
CI jobs, or publish private source data. A real Neo4j Community server runs in a
dedicated Docker Compose project. The image is pinned by digest.

## Questions being tested

- Can a related past attempt be found when the question uses different wording?
- Can the answer distinguish a proposal, a reported experiment, a measured result,
  a merge, a deployment, and a later reversal?
- Does every traversal obey its historical cutoff, including its supporting
  evidence, rather than allowing a future edge to rewrite an earlier state?
- Are environment, host, version, workload, and unresolved attribution retained?
- Does graph traversal improve over both journal-first search and the **same
  extracted facts** searched without a graph?

Import success, a seeded graph query, and retrieval accuracy are different results.
Extraction quality and answer quality must be evaluated separately. Missing archive
coverage is not evidence that an attempt never happened. A mutable session summary
does not establish what was known at an earlier capture time.

## Private artifacts

Keep inventories, originals, questions, gold annotations, graph authentication,
and detailed receipts outside this repository in a directory with mode `0700`.
Files containing source data use `0600`. Do not pass service credentials on command
lines, store them in the experiment, or create a production conversation for a test.

The authorized export starts with a frozen, user/folder-scoped Supabase inventory.
`export_archive.py` reads that inventory and downloads only its committed segments
through an existing authorized SSH host. The backend's credentials remain inside
its process environment. Every downloaded object is checked against its original
byte length and SHA-256, including legacy gzip storage. A receipt records missing
or corrupt objects. The export performs no database or Storage writes.

```bash
python3 export_archive.py --objects /private/objects.json \
  --user-id USER_UUID --folder-id FOLDER_UUID --host AUTHORIZED_SSH_HOST \
  --output /private/originals.tar.gz
```

Generate a private env file with `NEO4J_AUTH=neo4j/<random-local-password>`, then:

```bash
docker compose --project-name kioku-c360-temporal-poc \
  --env-file /private/neo4j.env -f compose.yaml up -d
```

Only loopback ports `17474` and `17687` are published. The graph is disposable and
uses its own volume; production Supabase remains read-only. Stop with the same
Compose project and file. Do not use `--remove-orphans` or remove unrelated volumes.

## Evaluation contract

Freeze corpus hashes and a cutoff before extraction or evaluation. Separate the
question manifest from answer annotations; retrieval callers must not load gold.
Report development cases separately from questions held out before tuning. Compare
systems using identical scope, evidence, cutoffs, and result budgets. Include an
equal-facts nongraph baseline so improvements in extraction are not attributed to
the database engine. Preserve failures and abstentions in the denominator.

Measure temporal leakage, stale recommendations, unsupported status transitions,
provenance validity, retrieval coverage, answer completeness, abstention, and cold
and warm latency separately. Include restart, repeat-import, and cutoff boundary
checks. Original evidence remains authoritative; journal snapshots are discovery
hints with potentially revised summaries.

At least four hours of active investigation and testing are required for this
experiment. Elapsed waiting for downloads alone does not satisfy that requirement.
