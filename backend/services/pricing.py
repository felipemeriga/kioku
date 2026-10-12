"""Rough cost estimation for chat LLM usage (Settings usage view)."""

# approximate list prices (USD / 1M tokens) — update when provider pricing changes.
# Keyed by both the short route names used by the default Anthropic chat path
# ("sonnet"/"haiku") and the full model ids used when a user picks a BYOK model.
MODEL_PRICES: dict[str, dict[str, float]] = {
    # Anthropic
    "sonnet": {"input": 3.0, "output": 15.0},
    "haiku": {"input": 1.0, "output": 5.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
    # OpenAI
    "gpt-5": {"input": 1.25, "output": 10.0},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "o4-mini": {"input": 1.1, "output": 4.4},
    # DeepSeek
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated USD cost for input/output tokens on a model.

    Unknown / custom models return 0.0 — we don't guess a price for a model we
    don't have rates for; the UI then shows tokens with a $0 estimate rather
    than a misleading number."""
    price = MODEL_PRICES.get(model)
    if price is None:
        return 0.0
    return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000
