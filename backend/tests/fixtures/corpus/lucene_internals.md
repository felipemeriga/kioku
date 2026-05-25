# Lucene Internals

Apache Lucene is the foundational search library underlying Elasticsearch,
OpenSearch, and Apache Solr. Understanding Lucene's storage model explains
why Elasticsearch behaves the way it does at scale.

## Segments

Lucene stores an index as a collection of immutable segments. Each segment
is a self-contained mini-index with its own inverted file, stored fields,
and optional vector index. When documents are added, they accumulate in a
RAM buffer and are periodically flushed to disk as new segments.

Searches fan out across all segments and merge the results. Segment merging
runs in the background, combining small segments into larger ones to keep
the total segment count manageable and reduce query overhead.

Immutability is key: because segments never change after being written,
Lucene avoids complex concurrent write locking and can use OS-level read
caching aggressively. Deleted documents are recorded in a separate per-
segment deletion bitmap; the space is reclaimed only when a merge rewrites
the segment.

## The Inverted Index

Within each segment, Lucene maintains a term dictionary mapping each term to
its posting list — the list of document IDs (and optionally term frequencies
and positions) that contain the term. Posting lists are delta-encoded with
variable-byte or FOR-delta compression, keeping them compact on disk.

The term dictionary is stored as a Finite State Transducer (FST), which
maps terms to byte offsets in the postings file. FSTs support prefix lookups
efficiently and fit in memory even for very large vocabularies.

## Stored Fields vs. Doc Values

**Stored fields** allow original field values to be retrieved by document ID.
They are row-oriented and compressed in blocks — efficient for fetching a
full document but expensive for aggregations.

**Doc values** are column-oriented: all values for a given field are stored
together. This layout is efficient for sorting, grouping, and numeric
aggregations, because the system reads only the relevant column rather than
fetching entire documents.

## Near Real-Time Search

Lucene supports near real-time (NRT) search: a new `IndexReader` can be
opened on an in-progress writer to see documents that have been added but
not yet flushed to disk. Elasticsearch uses NRT readers to make indexed
documents visible within ~1 second of indexing by default.

## HNSW in Lucene

Since Lucene 9, each segment can contain an HNSW graph for vector fields.
Each segment maintains its own graph, and vector search fans out across
segment-level graphs the same way term queries fan out across segment-level
inverted files. This design means vector search works naturally within
Lucene's existing segment merge lifecycle.
