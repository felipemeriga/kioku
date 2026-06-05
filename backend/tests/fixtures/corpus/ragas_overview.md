# RAGAS: Retrieval-Augmented Generation Assessment

RAGAS is an open-source evaluation framework for RAG (Retrieval-Augmented
Generation) pipelines. It provides automated metrics that measure different
aspects of a RAG system without requiring manual human annotation for every
query.

## Core Metrics

### Faithfulness

Faithfulness measures whether the generated answer is grounded in the
retrieved context. An unfaithful answer contains claims not supported by the
retrieved passages — a form of hallucination. RAGAS computes this by
decomposing the answer into atomic statements and checking each statement
against the context using an LLM judge.

Score range: 0 (no statement supported) to 1 (all statements supported).

### Answer Relevancy

Answer relevancy measures whether the generated answer actually addresses the
question. RAGAS generates reverse questions from the answer and checks whether
they match the original question semantically. An answer that drifts off-topic
or is incomplete scores lower.

Score range: 0 to 1.

### Context Precision

Context precision measures whether the retrieved chunks that are actually
useful are ranked higher than irrelevant ones. This evaluates retrieval
ordering, not just which chunks were retrieved. An ideal retriever puts the
most relevant chunks at positions 1 and 2.

### Context Recall

Context recall measures whether all information needed to answer the question
was present in the retrieved context. It requires a ground-truth reference
answer: RAGAS checks how many claims in the reference are supported by the
retrieved chunks.

## Dataset Requirements

A RAGAS evaluation dataset contains at minimum:
- `question` — the user query
- `answer` — the generated response
- `contexts` — the list of retrieved chunks (as strings)
- `ground_truth` — a reference answer (required only for context recall)

## Running RAGAS

```python
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision

result = evaluate(
    dataset=dataset,
    metrics=[faithfulness, answer_relevancy, context_precision],
)
print(result.to_pandas())
```

RAGAS uses an LLM internally to judge statements. The default is OpenAI's
GPT-4, but it can be configured to use any LLM via LangChain or LlamaIndex
adapters, including Claude models.

## Limitations

- LLM-based metrics have non-determinism — scores vary slightly between runs.
- Faithfulness can be fooled when the generated answer paraphrases the context
  very closely; the LLM judge may not catch semantic shifts.
- Context recall requires a ground-truth answer, which must be hand-authored
  or sourced from a curated QA dataset.

## Use in Continuous Evaluation

RAGAS is best run as part of a CI/CD regression suite with a fixed golden
dataset. Tracking metric deltas over time — rather than treating any single
run's absolute scores as ground truth — gives a reliable signal for whether
retrieval or generation quality has improved or regressed.
