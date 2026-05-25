"""RAG pipeline evaluation using RAGAS metrics."""

import asyncio
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor

import voyageai
from langsmith import traceable
from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.embeddings import BaseRagasEmbeddings
from ragas.llms import llm_factory
from ragas.metrics import (
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
    LLMContextPrecisionWithoutReference,
)

from services.embeddings import embed_query
from services.llm import MODEL_FOR_TASK, Task, complete, get_client
from services.search import search_documents

_executor = ThreadPoolExecutor(max_workers=1)

logger = logging.getLogger(__name__)


class VoyageEmbeddings(BaseRagasEmbeddings):
    """RAGAS-compatible wrapper around Voyage AI embeddings."""

    def __init__(self):
        self._client = voyageai.Client(api_key=os.environ["VOYAGE_API_KEY"])

    def embed_query(self, text: str) -> list[float]:
        result = self._client.embed([text], model="voyage-3", input_type="query")
        return result.embeddings[0]

    def embed_documents(self, texts: list) -> list:
        result = self._client.embed(texts, model="voyage-3", input_type="document")
        return result.embeddings

    async def aembed_query(self, text: str) -> list[float]:
        return self.embed_query(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)


def _get_ragas_llm():
    """Create a RAGAS-compatible LLM using Claude.

    Uses the shared, LangSmith-wrapped singleton from services.llm so RAGAS
    judge calls appear in tracing alongside the rest of the pipeline.
    """
    llm = llm_factory(MODEL_FOR_TASK[Task.EVAL_JUDGE], provider="anthropic", client=get_client())
    # Claude API rejects requests with both temperature and top_p set.
    # RAGAS defaults both; patch _map_provider_params to exclude top_p.
    _original_map = llm._map_provider_params

    def _anthropic_params():
        params = _original_map()
        # params is a pydantic model; convert to dict and drop top_p
        d = dict(params) if not isinstance(params, dict) else params
        d.pop("top_p", None)
        d["max_tokens"] = 4096
        return d

    llm._map_provider_params = _anthropic_params
    return llm


def _run_retrieval(query: str, user_id: str | None, root_folder_id: str | None) -> list[str]:
    """Run the full search pipeline and return retrieved context strings."""
    embedding = embed_query(query)
    results = search_documents(
        query_embedding=embedding,
        query_text=query,
        user_id=user_id,
        root_folder_id=root_folder_id,
    )
    return [r["content"] for r in results]


_GENERATION_SYSTEM = (
    "You answer technical questions using only the provided context.\n"
    "\n"
    "Rules:\n"
    "- Lead with the direct answer in the first sentence.\n"
    "- Keep the answer to 2-4 sentences. No preamble, no closing remarks.\n"
    "- No markdown headers, bullet lists, or code blocks unless the question "
    "explicitly asks for code.\n"
    "- Do not editorialize ('the tradeoff is clear', 'it is worth noting'). "
    "State facts.\n"
    "- If the context does not contain the answer, say so in one sentence."
)


def _run_generation(query: str, contexts: list[str]) -> str:
    """Generate an answer from retrieved contexts using Claude.

    Prompt is tuned for RAGAS answer_relevancy: direct answers induce
    hypothetical questions that match the original more closely than
    elaborated ones do.
    """
    context_text = "\n\n---\n\n".join(contexts)
    response = complete(
        task=Task.EVAL_JUDGE,
        max_tokens=512,
        system=_GENERATION_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": f"Context:\n{context_text}\n\nQuestion: {query}",
            }
        ],
    )
    return response.content[0].text.strip()


@traceable(name="evaluate_rag_pipeline", run_type="chain")
async def evaluate_rag_pipeline(
    test_questions: list[dict],
    user_id: str | None = None,
    root_folder_id: str | None = None,
) -> dict:
    """Evaluate the RAG pipeline with RAGAS metrics.

    Args:
        test_questions: List of dicts with keys:
            - question (str): The test question
            - ground_truth (str, optional): Expected answer for precision/recall metrics
        user_id: User ID to scope the search
        root_folder_id: Folder scope for search

    Returns:
        Dict with aggregate scores and per-question details.
    """
    llm = _get_ragas_llm()
    embeddings = VoyageEmbeddings()

    samples = []
    for item in test_questions:
        question = item["question"]
        ground_truth = item.get("ground_truth")

        # Run the full pipeline: retrieve + generate
        contexts = _run_retrieval(question, user_id, root_folder_id)
        response = _run_generation(question, contexts) if contexts else "No relevant context found."

        sample = SingleTurnSample(
            user_input=question,
            response=response,
            retrieved_contexts=contexts,
        )
        if ground_truth:
            sample.reference = ground_truth

        samples.append(sample)

    dataset = EvaluationDataset(samples=samples)

    # Select metrics based on whether ground truth is available
    has_ground_truth = any(item.get("ground_truth") for item in test_questions)

    metrics = [Faithfulness(), AnswerRelevancy()]
    if has_ground_truth:
        metrics.extend([ContextPrecision(), ContextRecall()])
    else:
        metrics.append(LLMContextPrecisionWithoutReference())

    # Run RAGAS evaluate in a separate thread with a standard asyncio event loop.
    # uvloop (used by uvicorn) doesn't support nested event loops, and RAGAS
    # internally calls asyncio.run/get_event_loop. We force the default policy
    # in the worker thread so RAGAS gets a plain asyncio loop.
    def _run_evaluate():
        asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return evaluate(dataset=dataset, metrics=metrics, llm=llm, embeddings=embeddings)
        finally:
            new_loop.close()

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_executor, _run_evaluate)

    # Build per-question details
    details = []
    scores_df = result.to_pandas()
    for i, item in enumerate(test_questions):
        row = scores_df.iloc[i].to_dict() if i < len(scores_df) else {}
        details.append(
            {
                "question": item["question"],
                "ground_truth": item.get("ground_truth"),
                "response": samples[i].response,
                "num_contexts": len(samples[i].retrieved_contexts),
                "scores": {
                    k: v
                    for k, v in row.items()
                    if k not in ("user_input", "response", "retrieved_contexts", "reference")
                },
            }
        )

    def _sanitize(v):
        """Replace NaN/Inf with None for JSON serialization."""
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v

    return {
        "aggregate": {k: _sanitize(v) for k, v in result._repr_dict.items()},
        "num_questions": len(test_questions),
        "details": [
            {
                **d,
                "scores": {k: _sanitize(v) for k, v in d["scores"].items()},
            }
            for d in details
        ],
    }
