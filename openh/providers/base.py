"""Provider protocol — every LLM provider implements this."""
from __future__ import annotations

from typing import Any, AsyncIterator, Protocol, TypedDict

from ..messages import Message, StreamEvent


class ToolSchema(TypedDict):
    name: str
    description: str
    input_schema: dict[str, Any]


class Provider(Protocol):
    name: str
    model: str

    def stream(
        self,
        messages: list[Message],
        system: str,
        tools: list[ToolSchema],
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        stop_sequences: list[str] | None = None,
        thinking_budget: int | None = None,
        provider_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        ...
