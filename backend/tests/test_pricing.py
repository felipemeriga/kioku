from services.pricing import estimate_cost_usd


class TestEstimateCost:
    def test_sonnet_math(self):
        # 1M input @ $3 + 1M output @ $15 = $18
        assert estimate_cost_usd("sonnet", 1_000_000, 1_000_000) == 18.0

    def test_haiku_math(self):
        # 1M input @ $1 + 1M output @ $5 = $6
        assert estimate_cost_usd("haiku", 1_000_000, 1_000_000) == 6.0

    def test_unknown_model_returns_zero(self):
        # Custom/unknown model → 0.0 (no guessed price; UI shows tokens only).
        assert estimate_cost_usd("mystery", 1_000_000, 500_000) == 0.0

    def test_byok_models_priced(self):
        # 1M in @ 0.27 + 1M out @ 1.10 = 1.37
        assert estimate_cost_usd("deepseek-chat", 1_000_000, 1_000_000) == 1.37
        assert estimate_cost_usd("gpt-4o", 1_000_000, 0) == 2.5
        assert estimate_cost_usd("claude-sonnet-4-6", 1_000_000, 0) == 3.0

    def test_zero_tokens(self):
        assert estimate_cost_usd("sonnet", 0, 0) == 0.0
