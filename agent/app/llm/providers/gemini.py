from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings
from app.core.logging import get_logger
from app.llm.base import LLMProvider
from app.llm.types import LLMConfig, LLMMessage, LLMResponse

logger = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)

# Google exposes an OpenAI-compatible REST endpoint for Gemini models
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class GeminiProvider(LLMProvider):
    """Google Gemini provider via the OpenAI-compatible endpoint.

    Structured output uses response_format json_schema (supported on
    gemini-2.0-flash and later). Internally reuses the openai SDK pointed
    at Google's base URL — no google-generativeai dependency needed.
    """

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=_GEMINI_BASE_URL,
        )

    def _resolve(self, config: LLMConfig | None) -> tuple[str, int, float]:
        return (
            (config and config.model) or settings.gemini_model,
            (config and config.max_tokens) or settings.llm_max_tokens,
            (config and config.temperature) if (config and config.temperature is not None)
            else settings.llm_temperature,
        )

    def _to_messages(self, messages: list[LLMMessage]) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in messages]

    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        model, max_tokens, temperature = self._resolve(config)

        response = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=self._to_messages(messages),
        )

        content = response.choices[0].message.content or ""
        return LLMResponse(
            content=content,
            model=model,
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
            raw=response.model_dump(),
        )

    async def complete_structured(
        self,
        messages: list[LLMMessage],
        response_model: type[T],
        config: LLMConfig | None = None,
    ) -> T:
        model, max_tokens, temperature = self._resolve(config)
        schema = response_model.model_json_schema()

        response = await self._client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=self._to_messages(messages),
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": schema,
                },
            },
        )

        raw_content = response.choices[0].message.content or "{}"
        return response_model.model_validate_json(raw_content)