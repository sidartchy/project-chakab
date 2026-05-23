from functools import lru_cache

from app.config import settings
from app.core.logging import get_logger
from app.llm.base import LLMProvider

logger = get_logger(__name__)

_PROVIDER_MAP = {
    "anthropic": "app.llm.providers.anthropic.AnthropicProvider",
    "openai": "app.llm.providers.openai.OpenAIProvider",
    "gemini": "app.llm.providers.gemini.GeminiProvider",
}


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    """Return a singleton LLM provider instance based on LLM_PROVIDER setting.

    Import is deferred so only the selected provider's SDK is actually used
    at runtime — no need to install all three API clients.
    """
    provider_name = settings.llm_provider.lower()
    dotted_path = _PROVIDER_MAP.get(provider_name)

    if not dotted_path:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider_name}'. "
            f"Valid options: {list(_PROVIDER_MAP.keys())}"
        )

    module_path, class_name = dotted_path.rsplit(".", 1)

    import importlib
    module = importlib.import_module(module_path)
    provider_class = getattr(module, class_name)
    instance: LLMProvider = provider_class()

    logger.info("llm.provider_initialized", provider=provider_name)
    return instance