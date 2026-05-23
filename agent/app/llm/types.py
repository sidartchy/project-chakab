from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class MessageRole(StrEnum):
    system = "system"
    user = "user"
    assistant = "assistant"


class LLMMessage(BaseModel):
    role: MessageRole
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    raw: dict[str, Any] = {}  # full provider response, useful for debugging


class LLMConfig(BaseModel):
    """Per-call overrides. Unset fields fall back to Settings defaults."""
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None