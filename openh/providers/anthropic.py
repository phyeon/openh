"""Anthropic Claude provider — wraps the official anthropic SDK streaming API."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic

from ..config import MAX_OUTPUT_TOKENS
from ..messages import (
    Message,
    MessageStop,
    StreamEvent,
    TextDelta,
    ToolUseDelta,
    ToolUseEnd,
    ToolUseStart,
    Usage,
)
from .base import ToolSchema


class AnthropicProvider:
    name: str = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self._client = AsyncAnthropic(api_key=api_key)

    async def stream(
        self,
        messages: list[Message],
        system: str,
        tools: list[ToolSchema],
    ) -> AsyncIterator[StreamEvent]:
        msg_dicts = [m.to_anthropic_dict() for m in messages]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": msg_dicts,
            "max_tokens": MAX_OUTPUT_TOKENS,
        }
        if tools:
            kwargs["tools"] = list(tools)

        # Buffers keyed by content_block index
        tool_buffers: dict[int, dict[str, Any]] = {}
        # Final usage emitted on message_stop
        in_tokens = 0
        out_tokens = 0
        stop_reason = "end_turn"

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                etype = getattr(event, "type", None)

                if etype == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        tool_buffers[event.index] = {
                            "id": block.id,
                            "name": block.name,
                            "json": "",
                        }
                        yield ToolUseStart(id=block.id, name=block.name)

                elif etype == "content_block_delta":
                    delta = event.delta
                    dtype = getattr(delta, "type", None)
                    if dtype == "text_delta":
                        yield TextDelta(text=delta.text)
                    elif dtype == "input_json_delta":
                        buf = tool_buffers.get(event.index)
                        if buf is not None:
                            buf["json"] += delta.partial_json
                            yield ToolUseDelta(id=buf["id"], partial_json=delta.partial_json)

                elif etype == "content_block_stop":
                    buf = tool_buffers.pop(event.index, None)
                    if buf is not None:
                        try:
                            parsed = json.loads(buf["json"]) if buf["json"] else {}
                        except json.JSONDecodeError:
                            parsed = {}
                        yield ToolUseEnd(id=buf["id"], name=buf["name"], input=parsed)

                elif etype == "message_delta":
                    usage = getattr(event, "usage", None)
                    if usage is not None:
                        out_tokens = getattr(usage, "output_tokens", out_tokens)
                    delta = getattr(event, "delta", None)
                    if delta is not None:
                        sr = getattr(delta, "stop_reason", None)
                        if sr:
                            stop_reason = sr

                elif etype == "message_start":
                    msg = getattr(event, "message", None)
                    if msg is not None:
                        usage = getattr(msg, "usage", None)
                        if usage is not None:
                            in_tokens = getattr(usage, "input_tokens", 0)

        yield Usage(input_tokens=in_tokens, output_tokens=out_tokens)
        yield MessageStop(stop_reason=stop_reason)
