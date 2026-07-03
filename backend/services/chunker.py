"""Recursive character text splitter for document chunking."""


def build_contextual_header(metadata: dict) -> str:
    """Build the per-chunk contextual header used for retrieval text shaping.

    Format: 'Source: file.pdf | Topic: ... | Keywords: a, b, c | Chunk 3 of 10'.

    Used at ingestion (prepended before embedding so vector search matches the
    contextualized text) AND at rerank time (the cross-encoder must score the
    same text shape that was indexed; otherwise it scores naked chunks and the
    contextual signal is lost).
    """
    parts = [f"Source: {metadata.get('source_filename', 'unknown')}"]
    topic = metadata.get("topic")
    if topic and topic != "unknown":
        parts.append(f"Topic: {topic}")
    keywords = metadata.get("keywords") or []
    if keywords:
        parts.append(f"Keywords: {', '.join(keywords)}")
    chunk_index = metadata.get("chunk_index")
    total_chunks = metadata.get("total_chunks")
    if chunk_index is not None and total_chunks is not None:
        parts.append(f"Chunk {chunk_index + 1} of {total_chunks}")
    notion_parent_path = metadata.get("notion_parent_path")
    if notion_parent_path:
        parts.append(f"Section: {notion_parent_path}")
    return " | ".join(parts)


def chunk_text(
    text: str,
    chunk_size: int = 2048,
    chunk_overlap: int = 200,
) -> list[str]:
    """Split text into chunks using recursive character splitting.

    Splits on double newline, single newline, sentence end, then space.
    Target: ~512 tokens per chunk (~2048 chars), ~50 token overlap (~200 chars).
    """
    separators = ["\n\n", "\n", ". ", " "]
    return _split_recursive(text, separators, chunk_size, chunk_overlap)


def _split_recursive(
    text: str,
    separators: list[str],
    chunk_size: int,
    chunk_overlap: int,
) -> list[str]:
    """Recursively split text using separator hierarchy."""
    if len(text) <= chunk_size:
        stripped = text.strip()
        return [stripped] if stripped else []

    separator = separators[0]
    remaining_separators = separators[1:] if len(separators) > 1 else separators

    parts = text.split(separator)

    chunks: list[str] = []
    current = ""

    for part in parts:
        candidate = current + separator + part if current else part
        if len(candidate) > chunk_size and current:
            stripped = current.strip()
            if stripped:
                if len(stripped) > chunk_size and remaining_separators != separators:
                    chunks.extend(
                        _split_recursive(stripped, remaining_separators, chunk_size, chunk_overlap)
                    )
                else:
                    chunks.append(stripped)
            if chunk_overlap > 0 and current:
                overlap_text = current[-chunk_overlap:]
                current = overlap_text + separator + part
            else:
                current = part
        else:
            current = candidate

    if current.strip():
        stripped = current.strip()
        if len(stripped) > chunk_size and remaining_separators != separators:
            chunks.extend(
                _split_recursive(stripped, remaining_separators, chunk_size, chunk_overlap)
            )
        else:
            chunks.append(stripped)

    return chunks
