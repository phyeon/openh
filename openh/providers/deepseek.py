"""DeepSeek provider.

DeepSeek's API is OpenAI-compatible (Chat Completions), so this subclasses
:class:`OpenAIProvider`, points the client at DeepSeek's ``base_url``, and
injects DeepSeek-specific request parameters.

Verified against the official docs (api-docs.deepseek.com) + live calls:
  * ``deepseek-v4-pro`` / ``deepseek-v4-flash`` support BOTH thinking and
    function calling at the same time. (The older "reasoning model" guide that
    lists Function Calling as unsupported predates V4 — a live tool call with
    thinking on returns ``finish_reason=tool_calls`` correctly.)
  * Thinking is toggled with the body parameter
    ``thinking = {"type": "enabled"|"disabled", "reasoning_effort": "high"|"max"}``.
    It is passed via the OpenAI SDK's ``extra_body``.
  * In *thinking* mode the model returns a separate ``reasoning_content`` (CoT).
    DeepSeek encodes the reasoning continuity into the GENUINE ``tool_call`` id
    it issues (ids look like ``call_00_...``). As long as that real id is echoed
    back on the follow-up request, thinking + tool use works WITHOUT re-sending
    ``reasoning_content`` — verified live across single, parallel, and multi-turn
    tool flows. (Only a *fabricated* tool_call id makes the API demand
    "reasoning_content ... must be passed back".) openh preserves the real id
    end to end (capture → persistence → replay), so the shared stream parser can
    keep dropping ``reasoning_content`` and thinking still works. Trade-off: the
    CoT itself is not displayed.
  * ``temperature``/``top_p`` have no effect in thinking mode (ignored, not an
    error); ``logprobs``/``top_logprobs`` would error but we never send them.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

from ..messages import Message, StreamEvent
from .base import ToolSchema
from .openai import OpenAIProvider

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekProvider(OpenAIProvider):
    name: str = "deepseek"

    # Thinking ON by default — it is the reason to pick v4-pro (SWE-bench 80.6 is
    # measured with thinking) and it works with tool use because DeepSeek carries
    # the reasoning continuity in the genuine tool_call id, which openh preserves
    # (so reasoning_content need not be re-sent). "high" is DeepSeek's default
    # effort. Override (incl. {"type": "disabled"} or "reasoning_effort": "max")
    # via provider_options["extra_body"]["thinking"].
    DEFAULT_THINKING: dict[str, Any] = {"type": "enabled", "reasoning_effort": "high"}

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key=api_key, model=model, base_url=DEEPSEEK_BASE_URL)

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
        # Inject the DeepSeek `thinking` toggle (unless the caller already set one).
        opts = dict(provider_options or {})
        extra_body = dict(opts.get("extra_body") or {})
        extra_body.setdefault("thinking", dict(self.DEFAULT_THINKING))
        opts["extra_body"] = extra_body
        async for event in super().stream(
            messages,
            system,
            tools,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            top_k=top_k,
            stop_sequences=stop_sequences,
            thinking_budget=thinking_budget,
            provider_options=opts,
        ):
            yield event
