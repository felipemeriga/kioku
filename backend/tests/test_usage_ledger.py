from types import SimpleNamespace
from unittest.mock import patch

from services.usage_ledger import UsageAttribution, UsageCollector, collect_usage, usage_row


def _message(model="claude-haiku-4-5-20251001"):
    return SimpleNamespace(
        id="msg_123",
        model=model,
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=200,
            cache_creation_input_tokens=3000,
            cache_read_input_tokens=4000,
            cache_creation=SimpleNamespace(
                ephemeral_5m_input_tokens=2000,
                ephemeral_1h_input_tokens=1000,
            ),
        ),
    )


def test_prices_all_anthropic_usage_categories_without_double_counting():
    row = usage_row(
        _message(),
        UsageAttribution("user", "chat", "answer", response_id="response", round_number=2),
    )
    assert row["provider_message_id"] == "msg_123"
    assert row["response_id"] == "response"
    assert row["round_number"] == 2
    assert row["cache_write_5m_tokens"] == 2000
    assert row["cache_write_1h_tokens"] == 1000
    assert row["cache_read_tokens"] == 4000
    # $0.001 base + $0.001 output + $0.0025 5m write + $0.002 1h
    # write + $0.0004 cache read.
    assert row["list_cost_usd"] == "0.0069"


def test_unknown_model_is_unpriced_instead_of_guessing():
    row = usage_row(_message("claude-unknown"), UsageAttribution("user", "mihari", "review"))
    assert row["list_cost_usd"] is None
    assert row["price_version"] is None


def test_cache_write_without_ttl_breakdown_defaults_to_five_minutes():
    message = _message()
    message.usage.cache_creation = None
    row = usage_row(message, UsageAttribution("user", "mihari", "review"))
    assert row["cache_write_5m_tokens"] == 3000
    assert row["cache_write_1h_tokens"] == 0


def test_subscription_completion_does_not_duplicate_api_usage_rows():
    from services.llm import Task, complete

    collector = UsageCollector()
    with (
        patch("services.llm.native_completion", return_value=SimpleNamespace(content=[])) as native,
        patch("services.llm.get_client") as api,
    ):
        with collect_usage(
            UsageAttribution("user", "chat", "enrichment", response_id="response"), collector
        ):
            complete(task=Task.QUERY_REWRITE, messages=[{"role": "user", "content": "query"}])
    assert native.call_args.kwargs["fallback_scope"].owner_id == "user"
    api.assert_not_called()
    assert collector.rows == []
