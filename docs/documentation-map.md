# Repository documentation map

Inventory of tracked Markdown/reStructuredText plus the guides introduced by this
refresh. Test corpora, historical reports, and previews are intentionally retained
in place so links and benchmark inputs remain stable. Untracked local agent files
and personal design work are outside this PR.

| Document | Role | Maintenance rule |
| --- | --- | --- |
| [.superpowers/sdd/final-fixes-report.md](../.superpowers/sdd/final-fixes-report.md) | Historical record | Past report/presentation; not current setup or acceptance evidence |
| [.superpowers/test-loop.md](../.superpowers/test-loop.md) | Historical record | Past report/presentation; not current setup or acceptance evidence |
| [README.md](../README.md) | Maintained guide | Current entry point; update with merged behavior |
| [RELEASE.md](../RELEASE.md) | Maintained guide | Current entry point; update with merged behavior |
| [backend/README.md](../backend/README.md) | Maintained guide | Current entry point; update with merged behavior |
| [backend/eval/README.md](../backend/eval/README.md) | Maintained guide | Current entry point; update with merged behavior |
| [backend/eval/obol/SPEC.md](../backend/eval/obol/SPEC.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/01-product-overview.md](../backend/eval/obol/docs/01-product-overview.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/02-system-architecture.md](../backend/eval/obol/docs/02-system-architecture.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/03-domain-glossary.md](../backend/eval/obol/docs/03-domain-glossary.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/04-gateway-api-reference.md](../backend/eval/obol/docs/04-gateway-api-reference.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/05-ledger-model-and-invariants.md](../backend/eval/obol/docs/05-ledger-model-and-invariants.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/06-money-movement-and-fees.md](../backend/eval/obol/docs/06-money-movement-and-fees.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/07-event-catalog.md](../backend/eval/obol/docs/07-event-catalog.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/08-payouts-and-reconciliation.md](../backend/eval/obol/docs/08-payouts-and-reconciliation.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/09-security-and-compliance.md](../backend/eval/obol/docs/09-security-and-compliance.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/10-architecture-decision-records.md](../backend/eval/obol/docs/10-architecture-decision-records.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/11-integration-guide.md](../backend/eval/obol/docs/11-integration-guide.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/docs/12-sla-and-operations.md](../backend/eval/obol/docs/12-sla-and-operations.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/repos/obol-console/README.md](../backend/eval/obol/repos/obol-console/README.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/repos/obol-gateway/README.md](../backend/eval/obol/repos/obol-gateway/README.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/eval/obol/repos/obol-ledger/README.md](../backend/eval/obol/repos/obol-ledger/README.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/annoy_overview.md](../backend/tests/fixtures/corpus/annoy_overview.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/bm25_intro.md](../backend/tests/fixtures/corpus/bm25_intro.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/chunking_strategies.md](../backend/tests/fixtures/corpus/chunking_strategies.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/claude_tool_use.md](../backend/tests/fixtures/corpus/claude_tool_use.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/elasticsearch_query.md](../backend/tests/fixtures/corpus/elasticsearch_query.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/eval_methodology.md](../backend/tests/fixtures/corpus/eval_methodology.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/faiss_overview.md](../backend/tests/fixtures/corpus/faiss_overview.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/hnsw_indexes.md](../backend/tests/fixtures/corpus/hnsw_indexes.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/ivfflat_indexes.md](../backend/tests/fixtures/corpus/ivfflat_indexes.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/lucene_internals.md](../backend/tests/fixtures/corpus/lucene_internals.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/pgvector_setup.md](../backend/tests/fixtures/corpus/pgvector_setup.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/postgres_tsvector.md](../backend/tests/fixtures/corpus/postgres_tsvector.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/prompt_caching.md](../backend/tests/fixtures/corpus/prompt_caching.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/ragas_overview.md](../backend/tests/fixtures/corpus/ragas_overview.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/reranking_intro.md](../backend/tests/fixtures/corpus/reranking_intro.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/rrf_fusion.md](../backend/tests/fixtures/corpus/rrf_fusion.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/scann_overview.md](../backend/tests/fixtures/corpus/scann_overview.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/tfidf_basics.md](../backend/tests/fixtures/corpus/tfidf_basics.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [backend/tests/fixtures/corpus/voyage_embeddings.md](../backend/tests/fixtures/corpus/voyage_embeddings.md) | Evaluation fixture | Preserve benchmark inputs; not Kioku product guidance |
| [cli/README.md](../cli/README.md) | Maintained guide | Current entry point; update with merged behavior |
| [design-system/README.md](../design-system/README.md) | Maintained guide | Current entry point; update with merged behavior |
| [design-system/assets/Logos/README.md](../design-system/assets/Logos/README.md) | Design artifact | Historical board or asset snapshot |
| [design-system/components/AppLayout/README.md](../design-system/components/AppLayout/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/Avatar/README.md](../design-system/components/Avatar/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/BriefingPanel/README.md](../design-system/components/BriefingPanel/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/Button/README.md](../design-system/components/Button/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/Card/README.md](../design-system/components/Card/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/ChatArea/README.md](../design-system/components/ChatArea/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/ChatInput/README.md](../design-system/components/ChatInput/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/ChatPage/README.md](../design-system/components/ChatPage/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/Chip/README.md](../design-system/components/Chip/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/CliAuthPage/README.md](../design-system/components/CliAuthPage/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/ContextPanel/README.md](../design-system/components/ContextPanel/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/Divider/README.md](../design-system/components/Divider/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/DocumentCard/README.md](../design-system/components/DocumentCard/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/DocumentViewerDrawer/README.md](../design-system/components/DocumentViewerDrawer/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/DocumentationPanel/README.md](../design-system/components/DocumentationPanel/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/DocumentsPage/README.md](../design-system/components/DocumentsPage/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/ErrorBoundary/README.md](../design-system/components/ErrorBoundary/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/FolderDetailPage/README.md](../design-system/components/FolderDetailPage/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/FolderIntegrationsDialog/README.md](../design-system/components/FolderIntegrationsDialog/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/FolderTree/README.md](../design-system/components/FolderTree/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/GitHubBrandIcon/README.md](../design-system/components/GitHubBrandIcon/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/IconButton/README.md](../design-system/components/IconButton/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/IconRail/README.md](../design-system/components/IconRail/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/IngestionDrawer/README.md](../design-system/components/IngestionDrawer/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/InspectDialog/README.md](../design-system/components/InspectDialog/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/LearningsTimeline/README.md](../design-system/components/LearningsTimeline/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/LoginPage/README.md](../design-system/components/LoginPage/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/MessageBubble/README.md](../design-system/components/MessageBubble/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/MoveDialog/README.md](../design-system/components/MoveDialog/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/NavItem/README.md](../design-system/components/NavItem/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/NotionBrandIcon/README.md](../design-system/components/NotionBrandIcon/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/NotionConnectDialog/README.md](../design-system/components/NotionConnectDialog/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/NotionIntegrationSection/README.md](../design-system/components/NotionIntegrationSection/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/NotionSyncBanner/README.md](../design-system/components/NotionSyncBanner/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/Paper/README.md](../design-system/components/Paper/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/ScopePickerDialog/README.md](../design-system/components/ScopePickerDialog/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/SettingsPage/README.md](../design-system/components/SettingsPage/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/Tabs/README.md](../design-system/components/Tabs/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/TextField/README.md](../design-system/components/TextField/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/ThinkingBar/README.md](../design-system/components/ThinkingBar/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/Toast/README.md](../design-system/components/Toast/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/components/Tooltip/README.md](../design-system/components/Tooltip/README.md) | Preview snapshot | Offline component reference; verify frontend source |
| [design-system/mockups/neo-tokyo/README.md](../design-system/mockups/neo-tokyo/README.md) | Design artifact | Historical board or asset snapshot |
| [docs/README.md](../docs/README.md) | Maintained guide | Current entry point; update with merged behavior |
| [docs/agent-memory.md](../docs/agent-memory.md) | Maintained guide | Current entry point; update with merged behavior |
| [docs/architecture.md](../docs/architecture.md) | Maintained guide | Current entry point; update with merged behavior |
| [docs/change-status.md](../docs/change-status.md) | Maintained guide | Current entry point; update with merged behavior |
| [docs/development.md](../docs/development.md) | Maintained guide | Current entry point; update with merged behavior |
| [docs/documentation-map.md](../docs/documentation-map.md) | Maintained guide | Current entry point; update with merged behavior |
| [docs/integrations.md](../docs/integrations.md) | Maintained guide | Current entry point; update with merged behavior |
| [docs/manabi.md](../docs/manabi.md) | Maintained guide | Current entry point; update with merged behavior |
| [docs/operations.md](../docs/operations.md) | Maintained guide | Current entry point; update with merged behavior |
| [docs/superpowers/plans/2026-11-04-tsukai-consumer-acceptance.md](../docs/superpowers/plans/2026-11-04-tsukai-consumer-acceptance.md) | Design / plan record | Preserve decisions; current status is in change-status.md |
| [docs/superpowers/plans/2026-11-04-tsukai-consumers.md](../docs/superpowers/plans/2026-11-04-tsukai-consumers.md) | Design / plan record | Preserve decisions; current status is in change-status.md |
| [docs/superpowers/plans/2026-11-04-tsukai-mihari.md](../docs/superpowers/plans/2026-11-04-tsukai-mihari.md) | Design / plan record | Preserve decisions; current status is in change-status.md |
| [docs/superpowers/plans/2026-11-04-tsukai-runtime.md](../docs/superpowers/plans/2026-11-04-tsukai-runtime.md) | Design / plan record | Preserve decisions; current status is in change-status.md |
| [docs/superpowers/specs/2026-10-29-continuous-agent-memory-design.md](../docs/superpowers/specs/2026-10-29-continuous-agent-memory-design.md) | Design / plan record | Preserve decisions; current status is in change-status.md |
| [docs/superpowers/specs/2026-11-04-tsukai-runner-design.md](../docs/superpowers/specs/2026-11-04-tsukai-runner-design.md) | Design / plan record | Preserve decisions; current status is in change-status.md |
| [frontend/README.md](../frontend/README.md) | Maintained guide | Current entry point; update with merged behavior |
| [frontend/src/assets/os/LICENSE.md](../frontend/src/assets/os/LICENSE.md) | Maintained guide | Current entry point; update with merged behavior |
| [mihari/README.md](../mihari/README.md) | Maintained guide | Current entry point; update with merged behavior |
| [slides.md](../slides.md) | Historical record | Past report/presentation; not current setup or acceptance evidence |
| [tests/e2e/README.md](../tests/e2e/README.md) | Maintained guide | Current entry point; update with merged behavior |
| [tsukai/README.md](../tsukai/README.md) | Maintained guide | Current entry point; update with merged behavior |
| [tsukai/protocol/README.md](../tsukai/protocol/README.md) | Maintained guide | Current entry point; update with merged behavior |
