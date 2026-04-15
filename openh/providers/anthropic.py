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
from ..system_prompt import SYSTEM_PROMPT_DYNAMIC_BOUNDARY
from .base import ToolSchema

ANTHROPIC_BETA_HEADER = (
    "interleaved-thinking-2025-05-14,"
    "token-efficient-tools-2025-02-19,"
    "files-api-2025-04-14,"
    "effort-2025-11-24"
)

# Content block types that accept an ``cache_control`` field on the Anthropic
# Messages API.  A block with another type (or an unknown shape) is silently
# skipped rather than risking a 400 from the API.
_CACHEABLE_BLOCK_TYPES = frozenset(
    {"text", "tool_use", "tool_result", "image", "document"}
)


def _mark_block_for_caching(block: dict[str, Any]) -> bool:
    """In-place add an ephemeral ``cache_control`` marker to a content block.
    Returns True if the marker was applied, False if the block was skipped
    (unknown shape or type that rejects cache_control).
    """
    if not isinstance(block, dict):
        return False
    if block.get("type") not in _CACHEABLE_BLOCK_TYPES:
        return False
    block["cache_control"] = {"type": "ephemeral"}
    return True


def _mark_conversation_cache_breakpoints(msg_dicts: list[dict[str, Any]]) -> None:
    """Add ephemeral ``cache_control`` markers to the last content block of
    the two most recent messages.  This follows Anthropic's recommended
    pattern for long agent loops: a marker at the current tail caches every
    call inside the current turn, and a marker one message earlier keeps the
    previous turn's prefix cached even after new content is appended — so
    the cache compounds rather than evicting itself each iteration.

    Anthropic caps cache_control at 4 breakpoints per request.  Combined with
    the markers on ``system`` (1) and the last tool schema (1), this brings
    us to the full 4.

    Operates in-place on dicts produced by ``Message.to_anthropic_dict``; no-op
    if the structure is not recognised.
    """
    if not msg_dicts:
        return
    marked = 0
    for msg in reversed(msg_dicts):
        if marked >= 2:
            break
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list) or not content:
            continue
        last_block = content[-1]
        if _mark_block_for_caching(last_block):
            marked += 1


class AnthropicProvider:
    name: str = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self._client = AsyncAnthropic(
            api_key=api_key,
            default_headers={"anthropic-beta": ANTHROPIC_BETA_HEADER},
        )

    async def stream(
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
        msg_dicts = [m.to_anthropic_dict() for m in messages]
        # Cache breakpoints 1-2 (of 4 allowed): conversation history.  Two
        # markers on the tail of the message list turn every prior turn into
        # a cache read (~10% of input cost) and let the cache compound across
        # iterations of the tool-use loop.  Without these, every tool_use /
        # tool_result dance in a long session is re-billed at full input rate
        # on every single turn.
        _mark_conversation_cache_breakpoints(msg_dicts)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": msg_dicts,
            "max_tokens": int(max_tokens or MAX_OUTPUT_TOKENS),
        }
        # Cache breakpoint 3: system static part (handled inside).
        kwargs["system"] = self._build_system_blocks(system)
        if tools:
            # Cache breakpoint 4: tool schemas.  Claude-Code-style tool
            # definitions are easily 10-20k tokens; caching them cuts the
            # dominant per-turn cost once the first call seeds the cache.
            tools_list = [dict(t) for t in tools]
            if tools_list:
                tools_list[-1] = {
                    **tools_list[-1],
                    "cache_control": {"type": "ephemeral"},
                }
            kwargs["tools"] = tools_list
            kwargs["tool_choice"] = {
                "type": "auto",
                "disable_parallel_tool_use": False,
            }
        if temperature is not None:
            kwargs["temperature"] = float(temperature)
        if top_p is not None:
            kwargs["top_p"] = float(top_p)
        if top_k is not None:
            kwargs["top_k"] = int(top_k)
        if stop_sequences:
            kwargs["stop_sequences"] = list(stop_sequences)
        if thinking_budget is not None:
            try:
                budget = int(thinking_budget)
            except Exception:
                budget = 0
            if budget > 0:
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": budget,
                }
        if isinstance(provider_options, dict):
            for key, value in provider_options.items():
                if key not in kwargs and value is not None:
                    kwargs[key] = value

        # Buffers keyed by content_block index
        tool_buffers: dict[int, dict[str, Any]] = {}
        # Final usage emitted on message_stop
        in_tokens = 0
        out_tokens = 0
        cache_creation_tokens = 0
        cache_read_tokens = 0
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
                        cache_creation_tokens = getattr(
                            usage,
                            "cache_creation_input_tokens",
                            cache_creation_tokens,
                        )
                        cache_read_tokens = getattr(
                            usage,
                            "cache_read_input_tokens",
                            cache_read_tokens,
                        )
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
                            cache_creation_tokens = getattr(
                                usage,
                                "cache_creation_input_tokens",
                                cache_creation_tokens,
                            )
                            cache_read_tokens = getattr(
                                usage,
                                "cache_read_input_tokens",
                                cache_read_tokens,
                            )

        yield Usage(
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cache_creation_input_tokens=cache_creation_tokens,
            cache_read_input_tokens=cache_read_tokens,
        )
        yield MessageStop(stop_reason=stop_reason)

    @staticmethod
    def _build_system_blocks(system: str) -> str | list[dict[str, Any]]:
        if SYSTEM_PROMPT_DYNAMIC_BOUNDARY not in system:
            return system

        static_part, dynamic_part = system.split(SYSTEM_PROMPT_DYNAMIC_BOUNDARY, 1)
        blocks: list[dict[str, Any]] = []

        static_text = static_part.strip()
        if static_text:
            blocks.append(
                {
                    "type": "text",
                    "text": static_text,
                    "cache_control": {"type": "ephemeral"},
                }
            )

        dynamic_text = dynamic_part.strip()
        if dynamic_text:
            blocks.append({"type": "text", "text": dynamic_text})

        return blocks or system.replace(SYSTEM_PROMPT_DYNAMIC_BOUNDARY, "").strip()
