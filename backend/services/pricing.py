"""Rough cost estimation for chat LLM usage (Settings usage view)."""

# approximate list prices (USD / 1M tokens) — update when Anthropic pricing changes
MODEL_PRICES: dict[str, dict[str, float]] = {
    "sonnet": {"input": 3.0, "output": 15.0},
    "haiku": {"input": 1.0, "output": 5.0},
}

_FALLBACK = MODEL_PRICES["sonnet"]


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD cost for a number of input/output tokens on a model.

    Unknown models fall back to Sonnet pricing (the pricier of the two) so the
    estimate never under-reports an unrecognized model."""
    price = MODEL_PRICES.get(model, _FALLBACK)
    return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000
