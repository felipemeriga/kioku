# Ingestion latency budget (v2 — supersedes v1)

Revised after the worker upgrade: the ingestion latency budget is now
90 seconds end-to-end for a standard PDF, replacing the earlier 3-minute
budget. Parser allocation drops to 50 seconds, embedding to 25 seconds.
The v1 numbers remain only for historical comparison; capacity planning
must use the 90-second figure.
