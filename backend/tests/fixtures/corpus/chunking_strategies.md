# Chunking Strategies for RAG

Chunking is the process of splitting source documents into smaller passages for
ingestion into a retrieval system. The chunking strategy has a large impact on
retrieval quality because the system can only return what it has stored, and
LLM context windows are finite.

## Fixed-Token Chunking

The simplest strategy: split the document every N tokens, with an optional
overlap of M tokens between adjacent chunks.

```
[token 1 ... token 512 | overlap] [overlap | token 513 ... token 1024 | overlap] ...
```

**Parameters:**
- `chunk_size` — number of tokens per chunk. Common values: 256, 512, 1024.
- `chunk_overlap` — tokens shared between adjacent chunks. Prevents splitting
  a sentence at a boundary from losing context. Common values: 50–200 tokens.

**Pros:** Simple, deterministic, works on any text.
**Cons:** Ignores document structure. A chunk may begin or end mid-sentence,
mid-paragraph, or mid-section — reducing coherence.

## Sentence / Paragraph Chunking

Split on natural boundaries (sentences or paragraphs) rather than arbitrary
token counts. Implementations detect sentence boundaries with a rule-based
splitter or a sentence boundary detection model.

**Pros:** Chunks are semantically complete units.
**Cons:** Chunk sizes vary widely. A single paragraph can be 50 or 2000 tokens.
Very short chunks may not carry enough context to answer a question on their own.

## Semantic Chunking

Group adjacent sentences into chunks using their embedding similarity. Sentences
that are semantically related are grouped together; a new chunk begins when
the embedding similarity drops below a threshold.

**Pros:** Chunk boundaries align with topic shifts in the document.
**Cons:** Requires an embedding call per sentence during ingestion, which is
slower and more expensive than rule-based approaches.

## Parent Document Retrieval

A hybrid strategy: store small chunks for retrieval (high precision) but
return the larger parent passage to the LLM (more context):

1. Split the document into large parent chunks (e.g., 1000 tokens).
2. Split each parent into small child chunks (e.g., 256 tokens).
3. Index only child chunks in the vector store.
4. When a child chunk is retrieved, fetch its parent and return that to the LLM.

This gives the precision of small-chunk retrieval with the coherence of large-chunk
context.

## Contextual Headers

A technique for embedding: prepend a short generated description of where in the
document a chunk came from before embedding it.

```
"From 'Architecture Guide', section 'HNSW Configuration': {chunk_text}"
```

The header is embedded with the chunk, so vector search can use the document-level
context to resolve ambiguous chunks. This is particularly effective for
multi-document corpora where the same phrase means different things in different
documents.

## Chunking for Code

Code requires specialized chunking:
- Split on function or class boundaries, not token counts.
- Include the file path and function signature as header context.
- Avoid splitting a function across chunks; this destroys the semantic unit.

## Recommended Defaults

For general-purpose RAG on mixed document types:
- `chunk_size = 512`, `chunk_overlap = 64` as a starting baseline.
- Use contextual headers for multi-document corpora.
- Implement parent retrieval if the LLM frequently says "I don't have enough
  information" on questions that should be answerable.
