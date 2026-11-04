# Kioku documentation

Start with a maintained guide. The [complete documentation map](documentation-map.md)
accounts for repository guides, previews, design records, presentations, and test
corpora. These have different purposes; a design document is not a feature-status
or deployment report.

## By task

| Task | Guide |
| --- | --- |
| Understand Kioku / connect a repo | [Overview](../README.md), [CLI](../cli/README.md) |
| Run locally / contribute / validate | [Development](development.md) |
| Trace services, retrieval, and execution policy | [Architecture](architecture.md) |
| Deploy, migrate, drain, or troubleshoot | [Operations](operations.md) |
| Integrate REST, MCP, GitHub, Notion, or uploads | [Integrations](integrations.md) |
| Understand journals, learnings, and transcript work | [Agent memory](agent-memory.md) |
| Diagnose machine presence and inventory | [Manabi](manabi.md) |
| Check main versus open PRs | [Change status](change-status.md) |

## By surface

[Backend](../backend/README.md) · [Frontend](../frontend/README.md) ·
[CLI](../cli/README.md) · [Mihari](../mihari/README.md) ·
[Tsukai](../tsukai/README.md) · [Tsukai protocol](../tsukai/protocol/README.md) ·
[Design system](../design-system/README.md) ·
[Retrieval evaluation](../backend/eval/README.md) ·
[Manual E2E launcher](../tests/e2e/README.md)

## Documentation rules

- Describe merged behavior in maintained guides; record enablement/deployment
  separately. Link pending work through the dated change-status snapshot.
- Keep exact API schemas in source/OpenAPI and exact CLI options in command help.
  Avoid duplicate endpoint, version, or model lists that drift after releases.
- Keep design decisions and plans under `superpowers/` as records, with a status
  note pointing here. Do not rewrite an old proposal to imply it was implemented.
- Treat component previews as snapshots; use frontend source for current props,
  typography, and behavior.
- Preserve evaluation corpora and synthetic repositories. Editing their prose
  changes benchmark inputs, not just documentation.
- When changing navigation, verify relative links, source paths, code fences, and
  `git diff --check`. Use [development checks](development.md) for code changes.

This refactor is grounded in main at `b1ac57f` and the PR snapshot linked above.
It does not attest to production rollout or independently rerun PR-specific tests.
