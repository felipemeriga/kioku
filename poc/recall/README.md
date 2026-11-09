# Originals-only natural-language recall POC

Read-only experiment. No embeddings, journal index, maintained learnings, production search endpoint, migrations, or deployed changes. Raw transcripts, model responses and the interactive evidence review remain in a private directory outside Git.

## Frozen experiment

Four c360-lead Codex sessions, November 2–6, 2026: 3,354 displayable, non-inherited original records, 25,687,384 exported bytes. Every segment is read through the deployed original SHA-256/length validator. Snapshot checksum is in `summary.json`. This is five calendar days in one repository, not a large or cross-provider benchmark.

Twelve questions were written before retrieval. Nine have topic anchors; two ask about unsupported events, and one asks for unestablished deployment evidence. The planner receives only IDs/questions, never anchors, expected answers, this conversation, or the archive. Native Claude Sonnet runs without tools, MCP servers, hooks, auto-memory or session persistence in a separate directory. Its reported usage is retained privately.

Original record text is chunked into overlapping 1,400-character passages with a 1,000-character stride. BM25 compares (a) the question directly and (b) the question plus three model reformulations, fused using reciprocal rank fusion. Top five distinct record IDs are passed to an answer model. It may answer partially or abstain. Citations must name a record retrieved **for that question** and quote an exact substring of its supplied excerpt. The runner flags unusable answers; the review intentionally shows rejected output for inspection.

## Results

- Manual review: **8 acceptable / 3 limited / 1 rejected**. Reviewer was the implementing agent, not an independent judge. These are case assessments, not general accuracy estimates.
- Nine anchor probes: direct lexical retrieval **7/9**, reformulated **9/9**. Anchors check topic presence in top-five records, not whether a result is sufficient, true or authoritative. The anchor-reference scan is private; the model never receives it.
- Exact citation validation: **11/12**. This does not verify that the quoted passage entails every answer claim.
- Two absent-event controls and the deployment-proof question received cautious insufficient-evidence answers. No claim that absence from results proves an event never occurred.
- Twelve-question batch: **49,931 input tokens** including cache creation, **4,949 output tokens**, approximately **51 seconds** native model time plus **1.33 seconds** local retrieval after index construction. Native CLI reported **$0.2492 API-equivalent cost**; this is not an additional subscription charge or a billing quote.
- Export, corpus parsing/index construction, smoke test and follow-up calls are excluded from those batch figures. Source contents are indexed locally once; the complete archive is never sent to the model.

### What did not work

1. Related passages are not enough to reconcile a changing decision. The archive contains 3 GiB and 4 GiB settings in different stages; a five-passage answer does not establish the final configuration or machine scope.
2. SDK package summaries were found, but the original failed link attempt/results were missing from the selected window. A relevant assistant report is not an independently verified tool observation.
3. A leak question leaned on the earlier disk investigation and missed later experiment context.
4. The latency answer borrowed a citation from the clock question in the same four-question batch. Validation rejected it. A controlled answer-only follow-up with exactly the same latency evidence isolated from other questions still failed exact citation checking, this time through escaped-character changes. Its partial answer remained incomplete. Neither retry replaces the original benchmark result.
5. Planner reformulations sometimes guessed Java/JVM terminology for a Go investigation. Query expansion is not automatically better for every case.
6. Native transcripts duplicate some messages in wrapper records and can contain recalled journals, memory files or documentation in tool outputs. There was no **separate** summary index, but this corpus is not purified raw measurements. Truncated upstream outputs and external files not in the archive remain evidence limits.

## Conclusion

Natural-language reformulation over lexical originals is a useful candidate-discovery baseline. This POC does not establish reliable autonomous recollection or prove embeddings unnecessary. Before adding embeddings, test neighboring turns, command/result pairing, scoped chronology, deterministic source spans, and independent held-out questions. Larger archives, Claude sessions, ambiguity, false negatives and prompt injection need separate evaluation. Do not turn this script into a production global Storage scan: production would need a scoped search index and incremental processing.

## Run

Python standard library and an authenticated native `claude` CLI are required; no API keys are embedded. Snapshot export uses the existing `meriga-server` SSH alias and backend's scoped read-only store. It reads production but never publishes or modifies originals.

```sh
mkdir -m 700 /absolute/private-directory
python3 poc/recall/export_snapshot.py --folder YOUR_FOLDER_UUID --output /absolute/private-directory/snapshot.jsonl
python3 poc/recall/recall.py --private /absolute/private-directory --run
python3 poc/recall/recall.py --private /absolute/private-directory --query "Have we already tried reducing the heap budget?"
python3 -m unittest discover -s poc/recall
```

Use `summary.json` for the frozen aggregate result. `review.py` regenerates the private HTML for **this specific audited run**, requiring its private `anchor-reference.json`, retrieval and answer artifacts. Its audit labels are manually recorded, not an automatic evaluator for arbitrary future runs. Model cache filenames bind both system prompt and request payload; later runs may differ. Raw originals are never committed. Additional private model checks include one Portuguese question and the isolated latency follow-up.
