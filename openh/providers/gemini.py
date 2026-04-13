"""Gemini provider — translates Anthropic message format ↔ Gemini Content."""
from __future__ import annotations

from typing import Any, AsyncIterator

from google import genai
from google.genai import types as gtypes

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

    @staticmethod
    def _normalize_model_name(model: str) -> str:
        name = str(model or "").strip()
        if name.startswith("models/"):
            name = name[len("models/") :]
        if name.startswith("google/"):
            name = name.split("/", 1)[1]
        if "gemini" not in name.lower():
            raise RuntimeError(
                f"Gemini provider only supports Gemini models, got: {model}"
            )
        return name

    @staticmethod
    def _supports_thinking(model: str) -> bool:
        normalized = str(model or "")
        return (
            "2.5" in normalized
            or "3.0" in normalized
            or "3.1" in normalized
            or "gemini-3" in normalized
        )

    @staticmethod
    def _tool_use_id_for_name(name: str, occurrence: int) -> str:
        sanitized = "".join(
            ch if ch.isascii() and (ch.isalnum() or ch in {"_", "-"}) else "_"
            for ch in str(name or "")
        )
        base = sanitized or "tool"
        if occurrence == 0:
            return f"call_{base}"
        return f"call_{base}_{occurrence + 1}"

    @staticmethod
    def _looks_like_unsupported_optional_config(error_text: str) -> bool:
        lowered = str(error_text or "").lower()
        return (
            "not supported" in lowered
            or "unsupported" in lowered
            or "unknown field" in lowered
            or "invalid argument" in lowered
            or "invalid_argument" in lowered
        )

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
        raw = tool_use_id.removeprefix("call_")
        if not raw:
            return None
        if "_" in raw:
            candidate, suffix = raw.rsplit("_", 1)
            if candidate and suffix.isdigit():
                raw = candidate
        return raw or None

    @staticmethod
    def _map_finish_reason(reason: object) -> str:
        if hasattr(reason, "name"):
            reason = getattr(reason, "name")
        reason_str = str(reason or "").upper()
        if reason_str in {"FUNCTION_CALL", "TOOL_CODE"}:
            return "tool_use"
        if reason_str == "MAX_TOKENS":
            return "max_tokens"
        if reason_str in {"SAFETY", "RECITATION"}:
            return "content_filtered"
        if reason_str in {"STOP", "END_TURN", "FINISH_REASON_UNSPECIFIED", ""}:
            return "end_turn"
        return str(reason or "end_turn").lower()

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
        temperature: float | None = None,
        top_p: float | None = None,
        top_k: int | None = None,
        stop_sequences: list[str] | None = None,
        thinking_budget: int | None = None,
        provider_options: dict[str, Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        api_model = self._normalize_model_name(self.model)
        contents = self._to_gemini_contents(messages)
        extra_options = dict(provider_options or {})
        config_kwargs: dict[str, Any] = {"system_instruction": system}
        gemini_tools = self._to_gemini_tools(tools)
        if gemini_tools is not None:
            config_kwargs["tools"] = gemini_tools
            config_kwargs["tool_config"] = extra_options.pop(
                "tool_config",
                gtypes.ToolConfig(
                    function_calling_config=gtypes.FunctionCallingConfig(
                        mode=gtypes.FunctionCallingConfigMode.AUTO,
                    ),
                    include_server_side_tool_invocations=False,
                ),
            )
            config_kwargs["automatic_function_calling"] = extra_options.pop(
                "automatic_function_calling",
                gtypes.AutomaticFunctionCallingConfig(disable=True),
            )
        config_kwargs["max_output_tokens"] = int(max_tokens or MAX_OUTPUT_TOKENS)
        if temperature is not None:
            config_kwargs["temperature"] = float(temperature)
        if top_p is not None:
            config_kwargs["top_p"] = float(top_p)
        if top_k is not None:
            config_kwargs["top_k"] = int(top_k)
        if stop_sequences:
            config_kwargs["stop_sequences"] = list(stop_sequences)
        resolved_thinking_budget = (
            thinking_budget
            if thinking_budget is not None
            else getattr(self, "thinking_budget", None)
        )
        if (
            resolved_thinking_budget is not None
            and self._supports_thinking(api_model)
        ):
            try:
                budget = int(resolved_thinking_budget)
            except Exception:
                budget = 0
            if budget > 0:
                config_kwargs["thinking_config"] = gtypes.ThinkingConfig(
                    include_thoughts=True,
                    thinking_budget=budget,
                )
        if extra_options:
            for key, value in extra_options.items():
                if key not in config_kwargs and value is not None:
                    config_kwargs[key] = value

        in_tokens = 0
        out_tokens = 0
        stop_reason = "end_turn"
        emitted_tool_use = False
        emitted_text = False
        tool_name_counts: dict[str, int] = {}
        pending_tool_calls: dict[int, tuple[str, str, dict[str, Any], Any]] = {}

        # Retry on transient errors (503, 429, etc.)
        import asyncio as _aio
        stream = None
        config_variants: list[dict[str, Any]] = [dict(config_kwargs)]
        if "automatic_function_calling" in config_kwargs:
            relaxed = dict(config_kwargs)
            relaxed.pop("automatic_function_calling", None)
            config_variants.append(relaxed)
        if "tool_config" in config_kwargs:
            fallback = dict(config_kwargs)
            fallback.pop("automatic_function_calling", None)
            fallback.pop("tool_config", None)
            config_variants.append(fallback)

        last_exc: Exception | None = None
        for variant in config_variants:
            config = gtypes.GenerateContentConfig(**variant)
            for _attempt in range(3):
                try:
                    stream = await self._client.aio.models.generate_content_stream(
                        model=api_model,
                        contents=contents,
                        config=config,
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    err_str = str(exc)
                    if _attempt < 2 and (
                        "503" in err_str
                        or "429" in err_str
                        or "UNAVAILABLE" in err_str
                        or "overloaded" in err_str.lower()
                    ):
                        await _aio.sleep(2 ** (_attempt + 1))
                        continue
                    if self._looks_like_unsupported_optional_config(err_str):
                        break
                    raise RuntimeError(f"Gemini request failed: {exc}") from exc
            if stream is not None:
                break
        if stream is None:
            if last_exc is not None:
                raise RuntimeError(f"Gemini request failed: {last_exc}") from last_exc
            raise RuntimeError("Gemini request failed: stream could not be created")

        async for chunk in stream:
            usage = getattr(chunk, "usage_metadata", None)
            if usage is not None:
                in_tokens = getattr(usage, "prompt_token_count", in_tokens) or in_tokens
                out_tokens = (
                    getattr(usage, "candidates_token_count", out_tokens) or out_tokens
                )

            candidates = getattr(chunk, "candidates", None) or []
            for cand in candidates:
                finish_reason = getattr(cand, "finish_reason", None)
                mapped_finish_reason = self._map_finish_reason(finish_reason)
                if mapped_finish_reason != "end_turn" or finish_reason:
                    stop_reason = mapped_finish_reason
                content = getattr(cand, "content", None)
                if content is None:
                    continue
                for part_idx, part in enumerate(content.parts or []):
                    text = getattr(part, "text", None)
                    fc = getattr(part, "function_call", None)
                    if text:
                        emitted_text = True
                        yield TextDelta(text=text)
                    if fc is not None:
                        emitted_tool_use = True
                        name = getattr(fc, "name", "") or "tool"
                        existing = pending_tool_calls.get(part_idx)
                        if existing is not None and existing[1] == name:
                            tool_id = existing[0]
                        else:
                            occurrence = tool_name_counts.get(name, 0)
                            tool_id = self._tool_use_id_for_name(name, occurrence)
                            tool_name_counts[name] = occurrence + 1
                        try:
                            args = dict(fc.args) if fc.args else {}
                        except Exception:
                            args = {}
                        pending_tool_calls[part_idx] = (tool_id, name, args, part)

        for part_idx in sorted(pending_tool_calls):
            tool_id, name, args, raw_part = pending_tool_calls[part_idx]
            yield ToolUseStart(id=tool_id, name=name)
            yield ToolUseEnd(id=tool_id, name=name, input=args, _raw_part=raw_part)

        if stop_reason == "end_turn" and emitted_tool_use and not emitted_text:
            stop_reason = "tool_use"
        elif stop_reason == "end_turn" and emitted_tool_use:
            stop_reason = "tool_use"

        yield Usage(input_tokens=in_tokens, output_tokens=out_tokens)
        yield MessageStop(stop_reason=stop_reason)


def _clean_schema_for_gemini(schema: dict[str, Any]) -> dict[str, Any]:
    """Strip JSON-Schema fields Gemini does not accept."""
    if not isinstance(schema, dict):
        return schema

    cleaned = dict(schema)
    for key in ("additionalProperties", "$schema", "default", "examples", "title"):
        cleaned.pop(key, None)

    schema_type = cleaned.get("type")
    if isinstance(schema_type, str):
        schema_type = schema_type.lower()
    else:
        schema_type = None

    enum_values = cleaned.get("enum")
    if isinstance(enum_values, list) and any(isinstance(item, (int, float)) for item in enum_values):
        cleaned["enum"] = [str(item) for item in enum_values]
        cleaned["type"] = "string"
        schema_type = "string"

    if schema_type == "object":
        props = cleaned.get("properties")
        if isinstance(props, dict):
            cleaned["properties"] = {
                key: _clean_schema_for_gemini(value)
                for key, value in props.items()
            }
        prop_keys = set(cleaned.get("properties", {}).keys()) if isinstance(cleaned.get("properties"), dict) else set()
        required = cleaned.get("required")
        if isinstance(required, list):
            cleaned["required"] = [
                key for key in required
                if isinstance(key, str) and key in prop_keys
            ]
    else:
        cleaned.pop("properties", None)
        cleaned.pop("required", None)

    if schema_type == "array":
        items = cleaned.get("items")
        if isinstance(items, dict):
            sanitized_items = _clean_schema_for_gemini(items)
            if isinstance(sanitized_items, dict) and "type" not in sanitized_items:
                sanitized_items["type"] = "string"
            cleaned["items"] = sanitized_items

    return cleaned
