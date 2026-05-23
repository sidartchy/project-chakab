from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.llm.types import LLMMessage, LLMResponse, MessageRole


@pytest.fixture(autouse=True)
def clear_provider_cache():
    """Reset the lru_cache between tests so provider changes take effect."""
    from app.llm.factory import get_llm_provider
    get_llm_provider.cache_clear()
    yield
    get_llm_provider.cache_clear()


def test_factory_returns_anthropic(monkeypatch):
    monkeypatch.setattr("app.config.settings.llm_provider", "anthropic")
    monkeypatch.setattr("app.config.settings.anthropic_api_key", "test-key")

    from app.llm.factory import get_llm_provider
    from app.llm.providers.anthropic import AnthropicProvider

    with patch("anthropic.AsyncAnthropic"):
        provider = get_llm_provider()
    assert isinstance(provider, AnthropicProvider)


def test_factory_returns_openai(monkeypatch):
    monkeypatch.setattr("app.config.settings.llm_provider", "openai")
    monkeypatch.setattr("app.config.settings.openai_api_key", "test-key")

    from app.llm.factory import get_llm_provider
    from app.llm.providers.openai import OpenAIProvider

    with patch("openai.AsyncOpenAI"):
        provider = get_llm_provider()
    assert isinstance(provider, OpenAIProvider)


def test_factory_returns_gemini(monkeypatch):
    monkeypatch.setattr("app.config.settings.llm_provider", "gemini")
    monkeypatch.setattr("app.config.settings.gemini_api_key", "test-key")

    from app.llm.factory import get_llm_provider
    from app.llm.providers.gemini import GeminiProvider

    with patch("openai.AsyncOpenAI"):
        provider = get_llm_provider()
    assert isinstance(provider, GeminiProvider)


def test_factory_raises_on_unknown_provider(monkeypatch):
    monkeypatch.setattr("app.config.settings.llm_provider", "unknown_provider")

    from app.llm.factory import get_llm_provider

    with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
        get_llm_provider()