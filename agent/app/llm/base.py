from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel

from app.llm.types import LLMConfig, LLMMessage, LLMResponse

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """Base class for all LLM provider implementations.

    To add a new provider:
      1. Create app/llm/providers/myprovider.py
      2. Subclass LLMProvider and implement both abstract methods
      3. Register it in app/llm/factory.py
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        config: LLMConfig | None = None,
    ) -> LLMResponse:
        """Send messages and return a plain-text response."""
        ...

    @abstractmethod
    async def complete_structured(
        self,
        messages: list[LLMMessage],
        response_model: type[T],
        config: LLMConfig | None = None,
    ) -> T:
        """Send messages and parse the response into a typed Pydantic model.

        Providers implement this via their native structured output mechanism:
          - Anthropic: tool_use with a single schema tool
          - OpenAI:    response_format with json_schema
          - Gemini:    response_schema via OpenAI-compatible endpoint
        """
        ...

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _build_json_system_note(self, response_model: type[BaseModel]) -> str:
        """Appends a JSON instruction to the system prompt so all providers
        produce output that matches response_model's schema."""
        schema = response_model.model_json_schema()
        return (
            "\n\nYou MUST respond with a single JSON object that strictly matches "
            f"this JSON Schema (no extra keys, no markdown fences):\n{schema}"
        )