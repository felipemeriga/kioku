# Prompt Caching

Prompt caching is a feature offered by some LLM API providers that allows a
prefix of the prompt to be stored on the server between API calls. On
subsequent calls where the same prefix is used, the provider skips
recomputing key-value (KV) attention states for the cached portion, reducing
both latency and cost.

## How It Works

During the prefill phase, a transformer model processes every token in the
prompt and computes attention keys and values for each layer. These KV states
are what makes autoregressive generation possible, but recomputing them on
every API call for a long system prompt is wasteful.

With prompt caching, the KV states for a designated prefix are stored in
the inference cluster's memory. When the same prefix arrives again, the model
reuses the stored states and processes only the non-cached suffix. This
reduces time-to-first-token (TTFT) roughly proportionally to the fraction of
the prompt that was cached.

## Anthropic Cache Control

Anthropic's Claude API allows callers to mark specific content blocks with a
`cache_control` parameter. When a block is marked as a cache breakpoint, the
API stores the KV state up to and including that block. Subsequent calls that
share the same prefix up to the breakpoint hit the cache.

```python
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": very_long_document,
                "cache_control": {"type": "ephemeral"}
            },
            {
                "type": "text",
                "text": "Summarize the above document."
            }
        ]
    }
]
```

Cached prefixes have a TTL of approximately 5 minutes. Cache hits are
reflected in the `usage` object with `cache_read_input_tokens` and
`cache_creation_input_tokens` fields.

## Cost Implications

Anthropic charges a reduced rate for cache-read tokens (typically ~10% of
the full input token cost) and a slightly elevated rate for cache-creation
tokens (typically ~25% above input cost). For workloads where a large system
prompt or document is reused across many queries, the net cost reduction
can be 60–90%.

## Optimal Usage Patterns

- **Long, stable system prompts** — place static instructions and tool
  definitions at the top of the prompt and mark them as a cache breakpoint.
- **Document Q&A** — place the document content in a cached user turn;
  each follow-up question arrives as a short non-cached suffix.
- **Few-shot examples** — if few-shot examples are fixed, cache them; leave
  the actual user query uncached.

## Limitations

Prompt caching is not useful when:
- Prompts change substantially between calls (cache miss).
- The prefix is very short (caching overhead may exceed savings).
- The TTL expires between calls (re-creation cost is charged again).
