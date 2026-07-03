import os

import voyageai
from langsmith import traceable


def get_voyage_client() -> voyageai.Client:
    return voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])


@traceable(name="embed_query", run_type="embedding")
def embed_query(text: str) -> list[float]:
    """Embed a single query string. Returns a 1024-dim vector."""
    client = get_voyage_client()
    result = client.embed([text], model="voyage-3", input_type="query")
    return result.embeddings[0]


@traceable(name="embed_document", run_type="embedding")
def embed_document(text: str) -> list[float]:
    """Embed a document chunk. Returns a 1024-dim vector."""
    client = get_voyage_client()
    result = client.embed([text], model="voyage-3", input_type="document")
    return result.embeddings[0]


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Batch-embed up to 128 texts per Voyage API call. Returns one vector per input, in order."""
    if not texts:
        return []
    client = get_voyage_client()
    out: list[list[float]] = []
    batch_size = 128
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = client.embed(batch, model="voyage-3", input_type="document")
        out.extend(resp.embeddings)
    return out
