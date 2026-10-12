"""resolve_chat: falls back to the kioku Anthropic path unless the user has
both a chosen provider/model AND a key for that provider."""

from unittest.mock import MagicMock, patch


def _sb(row: dict | None) -> MagicMock:
    sb = MagicMock()
    chain = sb.table.return_value.select.return_value.eq.return_value.limit.return_value
    chain.execute.return_value.data = [row] if row else []
    return sb


class TestResolveChat:
    def test_no_config_falls_back_to_anthropic(self):
        from services import ai_config

        cfg = ai_config.resolve_chat(_sb(None), "u1")
        assert cfg == {"provider": "anthropic", "model": None, "api_key": None}

    def test_provider_chosen_but_no_key_falls_back(self):
        from services import ai_config

        row = {"chat_provider": "openai", "chat_model": "gpt-4o", "openai_key_encrypted": None}
        cfg = ai_config.resolve_chat(_sb(row), "u1")
        assert cfg["provider"] == "anthropic" and cfg["api_key"] is None

    def test_byok_resolves_with_decrypted_key(self):
        from services import ai_config

        row = {
            "chat_provider": "deepseek",
            "chat_model": "deepseek-chat",
            "deepseek_key_encrypted": "kms:v1:blob",
        }
        with patch.object(ai_config, "decrypt_secret", return_value="sk-real") as dec:
            cfg = ai_config.resolve_chat(_sb(row), "u1")
        dec.assert_called_once_with("kms:v1:blob")
        assert cfg == {"provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-real"}


class TestSetProviderKey:
    def test_encrypts_and_upserts(self):
        from services import ai_config

        sb = MagicMock()
        with patch.object(ai_config, "encrypt_secret", return_value="kms:v1:enc") as enc:
            ai_config.set_provider_key(sb, "u1", "openai", "sk-plain")
        enc.assert_called_once_with("sk-plain")
        patch_arg = sb.table.return_value.upsert.call_args.args[0]
        assert patch_arg["openai_key_encrypted"] == "kms:v1:enc"
        assert patch_arg["user_id"] == "u1"

    def test_empty_key_clears(self):
        from services import ai_config

        sb = MagicMock()
        ai_config.set_provider_key(sb, "u1", "openai", "")
        patch_arg = sb.table.return_value.upsert.call_args.args[0]
        assert patch_arg["openai_key_encrypted"] is None

    def test_rejects_unknown_provider(self):
        from services import ai_config

        try:
            ai_config.set_provider_key(MagicMock(), "u1", "bogus", "k")
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


class TestIsReasoningModel:
    def test_flags(self):
        from services import ai_config

        assert ai_config.is_reasoning_model("deepseek", "deepseek-reasoner") is True
        assert ai_config.is_reasoning_model("deepseek", "deepseek-chat") is False
        assert ai_config.is_reasoning_model("openai", "gpt-4o") is False
        assert ai_config.is_reasoning_model("openai", "o4-mini") is True
