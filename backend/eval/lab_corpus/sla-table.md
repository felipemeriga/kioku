# Service Level Agreements — production targets

These are the agreed operational targets, reviewed quarterly.

| Service          | Metric              | Target        |
| ---------------- | ------------------- | ------------- |
| Search API       | p50 latency         | 220 ms        |
| Search API       | p99 latency         | 850 ms        |
| Document ingest  | end-to-end          | under 5 min   |
| Chat first token | p95                 | 2.5 s         |
| Platform         | monthly uptime      | 99.9 %        |
| Notion sync      | reconciliation lag  | under 30 min  |

## Notes

The search p99 target of 850 ms includes reranking. Breaching any target for
two consecutive weeks triggers a review; the on-call owner files the report.
