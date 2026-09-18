# Ingestion latency budget (v1)

Decision from the March planning round: the ingestion latency budget is
3 minutes end-to-end for a standard PDF — upload to searchable. The parser
gets 100 seconds of that budget, embedding gets 40 seconds, and the rest is
queue slack. Alerts fire at 80% of budget.
