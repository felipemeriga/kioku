# Merged behavior and open work

Reviewed against `origin/main` at `b1ac57f` and the GitHub open-PR list on
2026-11-04. This is a review snapshot, not a live deployment report. Dates in
migration filenames are ordering identifiers; they do not prove rollout dates.

## Main baseline

[PR #211](https://github.com/felipemeriga/kioku/pull/211) integrated Tsukai into main.
The reviewed head also includes authenticated subscription model discovery and
selection, stale-catalog restrictions, native chat recovery/cancellation fixes,
Mihari direct maintenance, and release/deployment updates. Tsukai is implemented;
its activation still depends on explicit configuration and credentials.

Daily agent journals, learnings, Manabi presence/inventory, and scoped repository
knowledge are already represented in main. The original transcript archive is not.

## Open PRs reviewed

| PR | Purpose | Documentation treatment |
| --- | --- | --- |
| [#214: original agent evidence](https://github.com/felipemeriga/kioku/pull/214) | Implementation of immutable originals, manifests, upload/retry, and transcript viewer; incorporates #213 | Pending feature; keep migration/enablement and outstanding Storage/PostgREST verification explicit |
| [#213: original-evidence specification](https://github.com/felipemeriga/kioku/pull/213) | Approved design and interactive illustrative prototype | Design/prototype, not deployed behavior; overlaps #214 |
| [#205: Tsukai routing/timing comparison](https://github.com/felipemeriga/kioku/pull/205) | Isolated UI/backend/MCP/Mihari routing experiments | Research evidence only; timings depend on workload and environment |
| [#203: native Claude Code POC](https://github.com/felipemeriga/kioku/pull/203) | Local/server native execution, resume, compaction, and accounting experiments | Research draft; do not merge/deploy as application implementation |

The research PRs predate the integrated implementation and are not the current
runtime contract. Their measurements do not establish current performance SLOs,
subscription cash charges, or production readiness.

## Updating this page

On the next documentation refresh, fetch main, inspect merged changes and every
open PR, and update this snapshot. Move a feature into current guides only after
verifying its merged implementation. Record deployment separately when verified.
The PR descriptions remain the source for branch-specific validation claims;
this documentation change does not rerun or independently certify those suites.
