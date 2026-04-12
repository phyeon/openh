"""OpenAI provider — wraps the official OpenAI chat completions streaming API."""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from ..config import MAX_OUTPUT_TOKENS
from ..messages import (
    DocumentBlock,
    ImageBlock,
    Message,
    MessageStop,
    StreamEvent,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseDelta,
    ToolUseEnd,
    ToolUseStart,
    Usage,
)
from .base import ToolSchema


class OpenAIProvider:
    name: str = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self._client = AsyncOpenAI(api_key=api_key)

    def _to_openai_messages(self, messages: list[Message], system: str) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = [
            {"role": "system", "content": system},
        ]
        for msg in messages:
            if msg.role == "assistant":
                text_chunks: list[str] = []
                tool_calls: list[dict[str, Any]] = []
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        if block.text:
                            text_chunks.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        tool_calls.append(
                            {
                                "id": block.id,
                                "type": "function",
                                "function": {
                                    "name": block.name,
                                    "arguments": json.dumps(block.input or {}, ensure_ascii=False),
                                },
                            }
                        )
                if text_chunks or tool_calls:
                    assistant_message: dict[str, Any] = {
                        "role": "assistant",
                        "content": "\n".join(text_chunks) if text_chunks else "",
                    }
                    if tool_calls:
                        assistant_message["tool_calls"] = tool_calls
                    converted.append(assistant_message)
                continue

            user_parts: list[dict[str, Any]] = []
            tool_messages: list[dict[str, Any]] = []
            for block in msg.content:
                if isinstance(block, TextBlock):
                    if block.text:
                        user_parts.append({"type": "text", "text": block.text})
                elif isinstance(block, ImageBlock):
                    user_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{block.media_type};base64,{block.data_base64}"
                            },
                        }
                    )
                elif isinstance(block, DocumentBlock):
                    user_parts.append(
                        {
                            "type": "text",
                            "text": "[Attached PDF omitted: OpenAI provider does not forward PDF blocks yet.]",
                        }
                    )
                elif isinstance(block, ToolResultBlock):
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.tool_use_id,
                            "content": block.content or "",
                        }
                    )
            if user_parts:
                converted.append({"role": "user", "content": user_parts})
            converted.extend(tool_messages)

        # Patch orphan tool_calls: if an assistant message has tool_calls but
        # the following messages don't include matching tool results, the API
        # rejects the request. Insert synthetic tool results for any orphans.
        patched: list[dict[str, Any]] = []
        for i, m in enumerate(converted):
            patched.append(m)
            tc_ids = [tc["id"] for tc in m.get("tool_calls", [])]
            if not tc_ids:
                continue
            # Collect tool result IDs that follow before the next assistant msg
            result_ids: set[str] = set()
            for j in range(i + 1, len(converted)):
                if converted[j].get("role") == "assistant":
                    break
                if converted[j].get("role") == "tool":
                    tid = converted[j].get("tool_call_id")
                    if tid:
                        result_ids.add(tid)
            for tc_id in tc_ids:
                if tc_id not in result_ids:
                    patched.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": "[interrupted]",
                    })
        return patched

    @staticmethod
    def _to_openai_tools(tools: list[ToolSchema]) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }
            for tool in tools
        ]

    async def stream(
        self,
        messages: list[Message],
        system: str,
        tools: list[ToolSchema],
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_openai_messages(messages, system),
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_completion_tokens": int(max_tokens or MAX_OUTPUT_TOKENS),
        }
        openai_tools = self._to_openai_tools(tools)
        if openai_tools is not None:
            payload["tools"] = openai_tools

        try:
            stream = await self._client.chat.completions.create(**payload)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc

        tool_buffers: dict[int, dict[str, Any]] = {}
        in_tokens = 0
        out_tokens = 0
        stop_reason = "end_turn"

        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                in_tokens = getattr(usage, "prompt_tokens", in_tokens) or in_tokens
                out_tokens = getattr(usage, "completion_tokens", out_tokens) or out_tokens

            for choice in getattr(chunk, "choices", []) or []:
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue
                if getattr(delta, "content", None):
                    yield TextDelta(text=delta.content)

                for tool_call in getattr(delta, "tool_calls", None) or []:
                    idx = getattr(tool_call, "index", 0)
                    buf = tool_buffers.setdefault(
                        idx,
                        {
                            "id": getattr(tool_call, "id", None) or f"openai_tool_{idx}",
                            "name": "",
                            "json": "",
                            "started": False,
                        },
                    )
                    if getattr(tool_call, "id", None):
                        buf["id"] = tool_call.id
                    fn = getattr(tool_call, "function", None)
                    if fn is not None and getattr(fn, "name", None):
                        buf["name"] = fn.name
                    if buf["name"] and not buf["started"]:
                        buf["started"] = True
                        yield ToolUseStart(id=buf["id"], name=buf["name"])
                    if fn is not None and getattr(fn, "arguments", None):
                        buf["json"] += fn.arguments
                        yield ToolUseDelta(id=buf["id"], partial_json=fn.arguments)

                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason == "tool_calls":
                    stop_reason = "tool_use"
                elif finish_reason == "length":
                    stop_reason = "max_tokens"
                elif finish_reason in {"stop", "end_turn"}:
                    stop_reason = "end_turn"

        for idx in sorted(tool_buffers):
            buf = tool_buffers[idx]
            if buf["name"] and not buf["started"]:
                yield ToolUseStart(id=buf["id"], name=buf["name"])
            try:
                parsed = json.loads(buf["json"]) if buf["json"] else {}
            except json.JSONDecodeError:
                parsed = {}
            if buf["name"]:
                yield ToolUseEnd(id=buf["id"], name=buf["name"], input=parsed)

        yield Usage(input_tokens=in_tokens, output_tokens=out_tokens)
        yield MessageStop(stop_reason=stop_reason)
