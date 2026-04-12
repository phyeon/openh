"""Gemini provider — translates Anthropic message format ↔ Gemini Content."""
from __future__ import annotations

import itertools
from typing import Any, AsyncIterator

from google import genai
from google.genai import types as gtypes

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
    ToolUseEnd,
    ToolUseStart,
    Usage,
)
from .base import ToolSchema


class GeminiProvider:
    name: str = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self._client = genai.Client(api_key=api_key)
        self._tool_id_counter = itertools.count(1)

    # ------------------------------------------------------------------ helpers

    def _next_tool_id(self) -> str:
        return f"gem_{next(self._tool_id_counter)}"

    def _to_gemini_contents(self, messages: list[Message]) -> list[gtypes.Content]:
        """Translate canonical Anthropic-format messages into Gemini Content list.

        One Content per Message; preserves turn order. tool_use → function_call,
        tool_result → function_response (must live on a user-role Content).
        """
        contents: list[gtypes.Content] = []
        import base64 as _b64
        for msg in messages:
            parts: list[gtypes.Part] = []
            for block in msg.content:
                if isinstance(block, TextBlock):
                    if block.text:
                        parts.append(gtypes.Part.from_text(text=block.text))
                elif isinstance(block, ImageBlock):
                    try:
                        raw = _b64.b64decode(block.data_base64)
                        parts.append(
                            gtypes.Part.from_bytes(data=raw, mime_type=block.media_type)
                        )
                    except Exception:
                        pass
                elif isinstance(block, DocumentBlock):
                    try:
                        raw = _b64.b64decode(block.data_base64)
                        parts.append(
                            gtypes.Part.from_bytes(data=raw, mime_type=block.media_type)
                        )
                    except Exception:
                        pass
                elif isinstance(block, ToolUseBlock):
                    # Use raw Part if available (preserves thought_signature for Gemini 3.x)
                    if getattr(block, "_raw_part", None) is not None:
                        parts.append(block._raw_part)
                    else:
                        parts.append(
                            gtypes.Part.from_function_call(name=block.name, args=block.input or {})
                        )
                elif isinstance(block, ToolResultBlock):
                    tool_name = self._lookup_tool_name(messages, block.tool_use_id) or "tool"
                    response_payload = {"content": block.content}
                    if block.is_error:
                        response_payload["is_error"] = True
                    parts.append(
                        gtypes.Part.from_function_response(name=tool_name, response=response_payload)
                    )
            if not parts:
                continue
            role = "model" if msg.role == "assistant" else "user"
            contents.append(gtypes.Content(role=role, parts=parts))
        return contents

    @staticmethod
    def _lookup_tool_name(messages: list[Message], tool_use_id: str) -> str | None:
        for m in messages:
            for b in m.content:
                if isinstance(b, ToolUseBlock) and b.id == tool_use_id:
                    return b.name
        return None

    @staticmethod
    def _to_gemini_tools(tools: list[ToolSchema]) -> list[gtypes.Tool] | None:
        if not tools:
            return None
        decls: list[gtypes.FunctionDeclaration] = []
        for t in tools:
            decls.append(
                gtypes.FunctionDeclaration(
                    name=t["name"],
                    description=t["description"],
                    parameters=_clean_schema_for_gemini(t["input_schema"]),
                )
            )
        return [gtypes.Tool(function_declarations=decls)]

    # ------------------------------------------------------------------ stream

    async def stream(
        self,
        messages: list[Message],
        system: str,
        tools: list[ToolSchema],
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        contents = self._to_gemini_contents(messages)
        config_kwargs: dict[str, Any] = {"system_instruction": system}
        gemini_tools = self._to_gemini_tools(tools)
        if gemini_tools is not None:
            config_kwargs["tools"] = gemini_tools
        if max_tokens is not None:
            config_kwargs["max_output_tokens"] = int(max_tokens)

        config = gtypes.GenerateContentConfig(**config_kwargs)

        in_tokens = 0
        out_tokens = 0
        stop_reason = "end_turn"
        emitted_tool_use = False
        emitted_text = False

        # Retry on transient errors (503, 429, etc.)
        import asyncio as _aio
        stream = None
        for _attempt in range(3):
            try:
                stream = await self._client.aio.models.generate_content_stream(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
                break
            except Exception as exc:  # noqa: BLE001
                err_str = str(exc)
                if _attempt < 2 and ("503" in err_str or "429" in err_str or "UNAVAILABLE" in err_str or "overloaded" in err_str.lower()):
                    yield TextDelta(text=f"[retrying ({_attempt+1}/3)… {err_str[:80]}]\n")
                    await _aio.sleep(2 ** (_attempt + 1))
                    continue
                yield TextDelta(text=f"[gemini error: {exc}]")
                yield Usage(input_tokens=0, output_tokens=0)
                yield MessageStop(stop_reason="error")
                return
        if stream is None:
            yield Usage(input_tokens=0, output_tokens=0)
            yield MessageStop(stop_reason="error")
            return

        async for chunk in stream:
            usage = getattr(chunk, "usage_metadata", None)
            if usage is not None:
                in_tokens = getattr(usage, "prompt_token_count", in_tokens) or in_tokens
                out_tokens = (
                    getattr(usage, "candidates_token_count", out_tokens) or out_tokens
                )

            candidates = getattr(chunk, "candidates", None) or []
            for cand in candidates:
                content = getattr(cand, "content", None)
                if content is None:
                    continue
                for part in (content.parts or []):
                    text = getattr(part, "text", None)
                    fc = getattr(part, "function_call", None)
                    if text:
                        emitted_text = True
                        yield TextDelta(text=text)
                    if fc is not None:
                        emitted_tool_use = True
                        tool_id = self._next_tool_id()
                        try:
                            args = dict(fc.args) if fc.args else {}
                        except Exception:
                            args = {}
                        yield ToolUseStart(id=tool_id, name=fc.name)
                        yield ToolUseEnd(id=tool_id, name=fc.name, input=args, _raw_part=part)

        if emitted_tool_use and not emitted_text:
            stop_reason = "tool_use"
        elif emitted_tool_use:
            stop_reason = "tool_use"

        yield Usage(input_tokens=in_tokens, output_tokens=out_tokens)
        yield MessageStop(stop_reason=stop_reason)


def _clean_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip JSON-Schema fields Gemini does not accept."""
    if not isinstance(schema, dict):
        return schema
    cleaned: dict[str, Any] = {}
    skip = {"$schema", "additionalProperties", "title", "examples", "default"}
    for k, v in schema.items():
        if k in skip:
            continue
        if k == "properties" and isinstance(v, dict):
            cleaned[k] = {pk: _clean_schema_for_gemini(pv) for pk, pv in v.items()}
        elif k == "items" and isinstance(v, dict):
            cleaned[k] = _clean_schema_for_gemini(v)
        else:
            cleaned[k] = v
    return cleaned
