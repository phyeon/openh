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

    @staticmethod
    def _use_responses_api(model: str) -> bool:
        model_name = str(model or "")
        return (
            model_name.startswith("o3")
            or model_name.startswith("o4")
            or model_name.startswith("gpt-5")
        )

    # ── Responses API helpers ──────────────────────────────────────────

    def _to_responses_input(self, messages: list[Message], system: str) -> list[dict[str, Any]]:
        """Convert internal messages to Responses API *input* format."""
        converted: list[dict[str, Any]] = [
            {"role": "developer", "content": system},
        ]
        for msg in messages:
            if msg.role == "assistant":
                # Text parts → assistant message
                text_chunks: list[str] = []
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        if block.text:
                            text_chunks.append(block.text)
                    elif isinstance(block, ToolUseBlock):
                        # Emit any preceding text first
                        if text_chunks:
                            converted.append({"role": "assistant", "content": "".join(text_chunks)})
                            text_chunks = []
                        converted.append({
                            "type": "function_call",
                            "call_id": block.id,
                            "name": block.name,
                            "arguments": json.dumps(block.input or {}, ensure_ascii=False),
                        })
                    elif isinstance(block, ToolResultBlock):
                        # Flush text
                        if text_chunks:
                            converted.append({"role": "assistant", "content": "".join(text_chunks)})
                            text_chunks = []
                        converted.append({
                            "type": "function_call_output",
                            "call_id": block.tool_use_id,
                            "output": block.content or "",
                        })
                if text_chunks:
                    converted.append({"role": "assistant", "content": "".join(text_chunks)})
                continue

            # user role
            user_parts: list[dict[str, Any]] = []
            for block in msg.content:
                if isinstance(block, TextBlock):
                    if block.text:
                        user_parts.append({"type": "input_text", "text": block.text})
                elif isinstance(block, ImageBlock):
                    user_parts.append({
                        "type": "input_image",
                        "image_url": f"data:{block.media_type};base64,{block.data_base64}",
                    })
                elif isinstance(block, DocumentBlock):
                    user_parts.append({
                        "type": "input_text",
                        "text": "[Attached PDF omitted: OpenAI Responses API does not forward PDF blocks yet.]",
                    })
                elif isinstance(block, ToolResultBlock):
                    # tool results from user messages
                    converted.append({
                        "type": "function_call_output",
                        "call_id": block.tool_use_id,
                        "output": block.content or "",
                    })
            if user_parts:
                converted.append({"role": "user", "content": user_parts})
        return converted

    @staticmethod
    def _to_responses_tools(tools: list[ToolSchema]) -> list[dict[str, Any]] | None:
        """Convert tool schemas to Responses API tool format."""
        if not tools:
            return None
        return [
            {
                "type": "function",
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            }
            for tool in tools
        ]

    async def _stream_responses(
        self,
        messages: list[Message],
        system: str,
        tools: list[ToolSchema],
        max_tokens: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        extra_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream using the OpenAI Responses API (gpt-5*, o3*, o4*)."""
        payload: dict[str, Any] = {
            "model": self.model,
            "input": self._to_responses_input(messages, system),
            "stream": True,
            "max_output_tokens": int(max_tokens or MAX_OUTPUT_TOKENS),
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if top_p is not None:
            payload["top_p"] = float(top_p)
        resp_tools = self._to_responses_tools(tools)
        if resp_tools is not None:
            payload["tools"] = resp_tools
        if extra_options:
            for key, value in extra_options.items():
                if key not in payload and value is not None:
                    payload[key] = value

        try:
            stream = await self._client.responses.create(**payload)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OpenAI Responses API request failed: {exc}") from exc

        # Track function call state per output item
        fc_buffers: dict[str, dict[str, Any]] = {}  # keyed by call_id
        in_tokens = 0
        out_tokens = 0
        cached_tokens = 0

        async for event in stream:
            event_type = getattr(event, "type", "")

            # ── Text deltas ──
            if event_type == "response.output_text.delta":
                delta_text = getattr(event, "delta", "")
                if delta_text:
                    yield TextDelta(text=delta_text)

            # ── Function call: new item added ──
            elif event_type == "response.output_item.added":
                item = getattr(event, "item", None)
                if item and getattr(item, "type", "") == "function_call":
                    call_id = getattr(item, "call_id", "") or ""
                    name = getattr(item, "name", "") or ""
                    fc_buffers[call_id] = {"name": name, "json": "", "started": False}
                    if name:
                        fc_buffers[call_id]["started"] = True
                        yield ToolUseStart(id=call_id, name=name)

            # ── Function call arguments delta ──
            elif event_type == "response.function_call_arguments.delta":
                delta_args = getattr(event, "delta", "")
                call_id = getattr(event, "item_id", "") or getattr(event, "call_id", "") or ""
                # Try to find the buffer
                buf = None
                if call_id in fc_buffers:
                    buf = fc_buffers[call_id]
                elif fc_buffers:
                    # fallback: use last buffer if call_id doesn't match
                    buf = list(fc_buffers.values())[-1]
                    call_id = list(fc_buffers.keys())[-1]
                if buf and delta_args:
                    buf["json"] += delta_args
                    yield ToolUseDelta(id=call_id, partial_json=delta_args)

            # ── Function call arguments done ──
            elif event_type == "response.function_call_arguments.done":
                call_id = getattr(event, "item_id", "") or getattr(event, "call_id", "") or ""
                arguments = getattr(event, "arguments", "")
                buf = fc_buffers.get(call_id)
                if buf is None and fc_buffers:
                    call_id = list(fc_buffers.keys())[-1]
                    buf = fc_buffers[call_id]
                if buf:
                    if not buf["started"] and buf["name"]:
                        buf["started"] = True
                        yield ToolUseStart(id=call_id, name=buf["name"])
                    try:
                        parsed = json.loads(arguments or buf["json"]) if (arguments or buf["json"]) else {}
                    except json.JSONDecodeError:
                        parsed = {}
                    yield ToolUseEnd(id=call_id, name=buf["name"], input=parsed)

            # ── Output item done (for function calls not caught above) ──
            elif event_type == "response.output_item.done":
                item = getattr(event, "item", None)
                if item and getattr(item, "type", "") == "function_call":
                    call_id = getattr(item, "call_id", "") or ""
                    name = getattr(item, "name", "") or ""
                    # If we haven't emitted ToolUseEnd yet
                    if call_id not in fc_buffers or not fc_buffers.get(call_id, {}).get("ended"):
                        arguments = getattr(item, "arguments", "")
                        try:
                            parsed = json.loads(arguments) if arguments else {}
                        except json.JSONDecodeError:
                            parsed = {}
                        if call_id not in fc_buffers:
                            yield ToolUseStart(id=call_id, name=name)
                        yield ToolUseEnd(id=call_id, name=name, input=parsed)

            # ── Response completed → usage ──
            elif event_type == "response.completed":
                resp = getattr(event, "response", None)
                if resp:
                    usage_obj = getattr(resp, "usage", None)
                    if usage_obj:
                        in_tokens = getattr(usage_obj, "input_tokens", 0) or 0
                        out_tokens = getattr(usage_obj, "output_tokens", 0) or 0
                        # OpenAI automatic prompt caching
                        details = getattr(usage_obj, "input_tokens_details", None)
                        if details:
                            cached_tokens = getattr(details, "cached_tokens", 0) or 0

        yield Usage(
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cache_read_input_tokens=cached_tokens,
        )
        yield MessageStop(stop_reason="end_turn")

    # ── Chat Completions helpers ─────────────────────────────────────

    def _to_openai_messages(self, messages: list[Message], system: str) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = [
            {"role": "system", "content": system},
        ]

        def _tool_result_messages(blocks: list[Any]) -> list[dict[str, Any]]:
            tool_messages: list[dict[str, Any]] = []
            for block in blocks:
                if isinstance(block, ToolResultBlock):
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": block.tool_use_id,
                            "content": block.content or "",
                        }
                    )
            return tool_messages

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
                        "content": "".join(text_chunks) if text_chunks else None,
                    }
                    if tool_calls:
                        assistant_message["tool_calls"] = tool_calls
                    converted.append(assistant_message)
                converted.extend(_tool_result_messages(msg.content))
                continue

            user_parts: list[dict[str, Any]] = []
            tool_messages = _tool_result_messages(msg.content)
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

    @staticmethod
    def _map_finish_reason(reason: str | None) -> str:
        if reason in {"tool_calls", "function_call"}:
            return "tool_use"
        if reason == "length":
            return "max_tokens"
        if reason == "content_filter":
            return "content_filtered"
        if reason in {"stop", "end_turn", None, ""}:
            return "end_turn"
        return str(reason)

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
        extra_options = dict(provider_options or {})
        if self._use_responses_api(self.model):
            async for event in self._stream_responses(
                messages, system, tools,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                extra_options=extra_options,
            ):
                yield event
            return
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._to_openai_messages(messages, system),
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": int(max_tokens or MAX_OUTPUT_TOKENS),
        }
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if top_p is not None:
            payload["top_p"] = float(top_p)
        if stop_sequences:
            payload["stop"] = list(stop_sequences)
        openai_tools = self._to_openai_tools(tools)
        if openai_tools is not None:
            payload["tools"] = openai_tools
            # Keep OpenAI on the same "auto + parallel" baseline as the
            # other providers so the shared agent loop sees the same kind of
            # tool batches whenever the model supports them.
            payload["tool_choice"] = extra_options.pop("tool_choice", "auto")
            payload["parallel_tool_calls"] = bool(
                extra_options.pop("parallel_tool_calls", True)
            )
        if extra_options:
            for key, value in extra_options.items():
                if key not in payload and value is not None:
                    payload[key] = value

        try:
            stream = await self._client.chat.completions.create(**payload)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc

        tool_buffers: dict[int, dict[str, Any]] = {}
        in_tokens = 0
        out_tokens = 0
        cached_tokens = 0
        stop_reason = "end_turn"

        async for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                in_tokens = getattr(usage, "prompt_tokens", in_tokens) or in_tokens
                out_tokens = getattr(usage, "completion_tokens", out_tokens) or out_tokens
                # OpenAI automatic prompt caching (Chat Completions)
                details = getattr(usage, "prompt_tokens_details", None)
                if details:
                    cached_tokens = getattr(details, "cached_tokens", cached_tokens) or cached_tokens

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
                stop_reason = self._map_finish_reason(finish_reason)

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

        yield Usage(
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cache_read_input_tokens=cached_tokens,
        )
        yield MessageStop(stop_reason=stop_reason)
