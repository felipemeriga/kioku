from services.pricing import estimate_cost_usd


class TestEstimateCost:
    def test_sonnet_math(self):
        # 1M input @ $3 + 1M output @ $15 = $18
        assert estimate_cost_usd("sonnet", 1_000_000, 1_000_000) == 18.0

    def test_haiku_math(self):
        # 1M input @ $1 + 1M output @ $5 = $6
        assert estimate_cost_usd("haiku", 1_000_000, 1_000_000) == 6.0

    def test_unknown_model_falls_back_to_sonnet(self):
        assert estimate_cost_usd("mystery", 1_000_000, 0) == estimate_cost_usd(
            "sonnet", 1_000_000, 0
        )

    def test_zero_tokens(self):
        assert estimate_cost_usd("sonnet", 0, 0) == 0.0
