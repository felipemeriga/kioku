"""Native list-equivalent counters; never represent subscription charges."""


def usage_record(result, attempt, previous=None):
    models = result.get("modelUsage") or {}
    fields = {
        "input_tokens": "inputTokens",
        "output_tokens": "outputTokens",
        "cache_read_tokens": "cacheReadInputTokens",
        "cache_creation_tokens": "cacheCreationInputTokens",
    }
    counters = {
        key: sum(m[raw] for m in models.values() if isinstance(m.get(raw), (int, float)))
        if models and all(isinstance(m.get(raw), (int, float)) for m in models.values())
        else None
        for key, raw in fields.items()
    }
    total = result.get("total_cost_usd")
    total = total if isinstance(total, (float, int)) and total >= 0 else None
    previous_cost = (previous or {}).get("last_cost")
    reset = previous_cost is not None and total is not None and total < previous_cost
    cost = total
    if previous_cost is not None and total is not None and not reset:
        cost = total - previous_cost
    old = (previous or {}).get("last_counters") or {}
    normalized = {}
    for key, value in counters.items():
        prior = old.get(key)
        normalized[key] = (
            value - prior
            if prior is not None and value is not None and value >= prior and not reset
            else value
        )
    return {
        "billing_mode": "subscription",
        "list_equivalent_usd": cost,
        **normalized,
        "model_usage": models,
        "counter_segment": attempt["counter_segment"],
        "counter_reset": reset,
        "complete": bool(
            total is not None
            and models
            and all(v is not None for v in counters.values())
            and not attempt["resume"]
        ),
        "native_total_cost_usd": total,
        "native_counters": counters,
        "attribution": "native_final"
        if not attempt["resume"]
        else "resume_counter_delta_uncertain",
    }
