import json
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from app.config import settings
from app.core.logging import get_logger
from app.llm.base import LLMProvider
from app.llm.types import LLMConfig, LLMMessage, LLMResponse, MessageRole

logger = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class AnthropicProvider(LLMProvider):
    """Claude provider via the official Anthropic Python SDK.

    Structured output is implemented with tool_use: we define a single tool
    whose input schema is the Pydantic model's JSON schema, then force the
    model to call it. This gives us reliable typed output without any
    third-party wrapper.
    """

    def __init__(self) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    def _resolve(self, config: LLMConfig | None) -> tuple[str, int, float]:
        return (
            (config and config.model) or settings.anthropic_model,
            (config and config.max_tokens) or settings.llm_max_tokens,
            (config and config.temperature) if (config and config.temperature is not None)
            else settings.llm_temperature,
        )

    def _split_system(
        self, messages: list[LLMMessage]
    ) -> tuple[str, list[dict[str, str]]]:
        """Anthropic requires the system prompt as a top-level parameter."""
        system = ""
        user_messages: list[dict[str, str]] = []
        for m in messages:
            if m.role == MessageRole.system:
                system = m.content
            else:
                user_messages.append({"role": m.role, "content": m.content})
        return system, user_messages

    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        model, max_tokens, temperature = self._resolve(config)
        system, user_messages = self._split_system(messages)

        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or anthropic.NOT_GIVEN,
            messages=user_messages,
        )

        content = response.content[0].text if response.content else ""
        return LLMResponse(
            content=content,
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            raw=response.model_dump(),
        )

    async def complete_structured(
        self,
        messages: list[LLMMessage],
        response_model: type[T],
        config: LLMConfig | None = None,
    ) -> T:
        model, max_tokens, temperature = self._resolve(config)
        system, user_messages = self._split_system(messages)

        tool_name = "structured_response"
        tool_def = {
            "name": tool_name,
            "description": (
                f"Return a structured response matching the {response_model.__name__} schema."
            ),
            "input_schema": response_model.model_json_schema(),
        }

        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or anthropic.NOT_GIVEN,
            messages=user_messages,
            tools=[tool_def],
            tool_choice={"type": "tool", "name": tool_name},
        )

        # Extract the tool_use block
        tool_block = next(
            (b for b in response.content if b.type == "tool_use"), None
        )
        if not tool_block:
            raise ValueError(
                f"Anthropic did not return a tool_use block. "
                f"Raw response: {response.model_dump()}"
            )

        return response_model.model_validate(tool_block.input)