"""Gemini provider — translates Anthropic message format ↔ Gemini Content."""
from __future__ import annotations

import hashlib
import json
import time
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
from ..system_prompt import SYSTEM_PROMPT_DYNAMIC_BOUNDARY
from .base import ToolSchema

# Explicit cache TTL.  One hour matches Anthropic's extended cache TTL so
# long coding sessions pay storage rather than re-creation whenever the user
# thinks between turns.  Format is Gemini's protobuf duration string.
_GEMINI_CACHE_TTL_SECONDS = 3600
_GEMINI_CACHE_TTL_STR = f"{_GEMINI_CACHE_TTL_SECONDS}s"

# Gemini rejects explicit cache creation below a model-specific token floor
# (typically 1024-4096).  After any failure we stop trying for the rest of
# the provider's lifetime rather than bombard the API on every turn.
_GEMINI_CACHE_DISABLE_AFTER_ERRORS = 2


def _split_static_dynamic_system(system: str) -> tuple[str, str]:
    """Split a ``build_system_prompt`` string on the dynamic boundary marker.
    Returns ``(static, dynamic)``; both may be empty.  The boundary literal
    itself is stripped.  If the marker is absent the whole prompt is treated
    as static so we do not accidentally regress existing behaviour.
    """
    text = system or ""
    if SYSTEM_PROMPT_DYNAMIC_BOUNDARY not in text:
        return text.strip(), ""
    static, dynamic = text.split(SYSTEM_PROMPT_DYNAMIC_BOUNDARY, 1)
    return static.strip(), dynamic.strip()


def _prepend_dynamic_context(
    contents: list["gtypes.Content"], dynamic_text: str
) -> list["gtypes.Content"]:
    """Return a new ``contents`` list with ``dynamic_text`` prepended to the
    first user-role message as a leading text Part.  If there is no user
    message yet, a fresh one is inserted at the front.

    Keeping the per-turn dynamic data (date, cwd, memory, …) out of
    ``system_instruction`` is what lets Gemini's implicit cache actually
    match across turns — the cache is keyed on the exact prompt prefix and
    any variation invalidates it.
    """
    if not dynamic_text:
        return contents
    preamble_part = gtypes.Part.from_text(text=dynamic_text)
    new_contents = list(contents)
    for idx, content in enumerate(new_contents):
        if content.role != "user":
            continue
        merged_parts = [preamble_part, *(content.parts or [])]
        new_contents[idx] = gtypes.Content(role="user", parts=merged_parts)
        return new_contents
    # No user message yet — inject one at the front so Gemini still sees
    # the dynamic context before the model starts responding.
    new_contents.insert(0, gtypes.Content(role="user", parts=[preamble_part]))
    return new_contents


class GeminiProvider:
    name: str = "gemini"

    def __init__(self, api_key: str, model: str) -> None:
        self.model = model
        self._client = genai.Client(api_key=api_key)
        # Explicit-caching state.  One cache per (model, system, tools)
        # fingerprint; we rebuild whenever any of those change and fall
        # back silently to implicit caching if the API refuses.
        self._cache_name: str | None = None
        self._cache_key: str | None = None
        self._cache_expires_at: float = 0.0
        self._cache_error_count: int = 0

    @staticmethod
    def _cache_fingerprint(
        api_model: str, static_system: str, tools: list[ToolSchema] | None
    ) -> str:
        h = hashlib.sha256()
        h.update(api_model.encode("utf-8"))
        h.update(b"\x1e")
        h.update((static_system or "").encode("utf-8"))
        h.update(b"\x1e")
        for t in tools or []:
            h.update(
                json.dumps(t, sort_keys=True, ensure_ascii=False).encode("utf-8")
            )
            h.update(b"\x1e")
        return h.hexdigest()[:16]

    async def _ensure_explicit_cache(
        self,
        *,
        api_model: str,
        static_system: str,
        gemini_tools: list[gtypes.Tool] | None,
        tool_config: Any | None,
    ) -> str | None:
        """Return the name of an active ``cachedContent`` covering the current
        static system instruction + tools, creating one if needed.  Returns
        None (and disables further attempts) on any failure — caller falls
        back to passing system/tools in the live request.
        """
        if self._cache_error_count >= _GEMINI_CACHE_DISABLE_AFTER_ERRORS:
            return None
        if not static_system and not gemini_tools:
            return None
        key = self._cache_fingerprint(api_model, static_system, None)
        # Hash with original tool schema dicts is tricky once we've converted
        # to Gemini Tool objects, but the static_system change already covers
        # the most volatile input; tool schemas almost never change mid-session.
        now = time.time()
        # Renew a little before TTL to avoid racing expiration mid-call.
        renewal_margin = 120.0
        if (
            self._cache_name
            and self._cache_key == key
            and now < self._cache_expires_at - renewal_margin
        ):
            return self._cache_name
        try:
            cfg_kwargs: dict[str, Any] = {"ttl": _GEMINI_CACHE_TTL_STR}
            if static_system:
                cfg_kwargs["system_instruction"] = static_system
            if gemini_tools:
                cfg_kwargs["tools"] = gemini_tools
                if tool_config is not None:
                    cfg_kwargs["tool_config"] = tool_config
            cache = await self._client.aio.caches.create(
                model=api_model,
                config=gtypes.CreateCachedContentConfig(**cfg_kwargs),
            )
        except Exception:
            # Most common reason is "content too small to cache" for the
            # chosen model; there's nothing we can do about it at the call
            # site so just step aside and let implicit caching handle it.
            self._cache_error_count += 1
            return None
        self._cache_name = getattr(cache, "name", None)
        self._cache_key = key
        self._cache_expires_at = now + _GEMINI_CACHE_TTL_SECONDS
        return self._cache_name

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
        # Keep system_instruction static across turns so Gemini's implicit
        # cache can key on it — any drift (today's date, cwd, memory, …)
        # invalidates the entire prompt prefix and re-bills full input rate.
        # Dynamic per-turn context rides on the first user message instead.
        static_system, dynamic_system = _split_static_dynamic_system(system)
        if dynamic_system:
            contents = _prepend_dynamic_context(contents, dynamic_system)
        extra_options = dict(provider_options or {})
        config_kwargs: dict[str, Any] = {}
        gemini_tools = self._to_gemini_tools(tools)
        tool_config: Any | None = None
        if gemini_tools is not None:
            tool_config = extra_options.pop(
                "tool_config",
                gtypes.ToolConfig(
                    function_calling_config=gtypes.FunctionCallingConfig(
                        mode=gtypes.FunctionCallingConfigMode.AUTO,
                    ),
                    include_server_side_tool_invocations=False,
                ),
            )
            # Automatic function calling is a per-call setting; it does not
            # live inside the explicit cache.
            config_kwargs["automatic_function_calling"] = extra_options.pop(
                "automatic_function_calling",
                gtypes.AutomaticFunctionCallingConfig(disable=True),
            )

        # Try explicit cachedContent first.  When it works every subsequent
        # call in the session sees system_instruction + tools at roughly 10%
        # of input cost.  On any failure we fall back to inline system/tools
        # (which still benefits from Gemini's implicit cache when the prompt
        # prefix happens to match).
        cache_name = await self._ensure_explicit_cache(
            api_model=api_model,
            static_system=static_system,
            gemini_tools=gemini_tools,
            tool_config=tool_config,
        )
        if cache_name is not None:
            config_kwargs["cached_content"] = cache_name
        else:
            if static_system:
                config_kwargs["system_instruction"] = static_system
            if gemini_tools is not None:
                config_kwargs["tools"] = gemini_tools
                if tool_config is not None:
                    config_kwargs["tool_config"] = tool_config
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
        if "cached_content" in config_kwargs:
            # Cache can be evicted / deleted server-side between turns.  If
            # that happens, rebuild a variant that carries the system / tool
            # definitions inline so the call still succeeds, and clear our
            # cached name so next turn re-creates.
            without_cache = dict(config_kwargs)
            without_cache.pop("cached_content", None)
            if static_system:
                without_cache["system_instruction"] = static_system
            if gemini_tools is not None:
                without_cache["tools"] = gemini_tools
                if tool_config is not None:
                    without_cache["tool_config"] = tool_config
            config_variants.append(without_cache)
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
            variant_uses_cache = "cached_content" in variant
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
            if stream is None and variant_uses_cache:
                # The cached_content reference failed — probably evicted
                # server-side.  Wipe local state so the next turn rebuilds.
                self._cache_name = None
                self._cache_key = None
                self._cache_expires_at = 0.0
            if stream is not None:
                break
        if stream is None:
            if last_exc is not None:
                raise RuntimeError(f"Gemini request failed: {last_exc}") from last_exc
            raise RuntimeError("Gemini request failed: stream could not be created")

        cached_tokens = 0
        async for chunk in stream:
            usage = getattr(chunk, "usage_metadata", None)
            if usage is not None:
                in_tokens = getattr(usage, "prompt_token_count", in_tokens) or in_tokens
                out_tokens = (
                    getattr(usage, "candidates_token_count", out_tokens) or out_tokens
                )
                # Gemini implicit caching: cached_content_token_count
                cached_tokens = (
                    getattr(usage, "cached_content_token_count", cached_tokens)
                    or cached_tokens
                )

            candidates = getattr(chunk, "candidates", None) or []
            for cand in candidates:
                finish_reason = getattr(cand, "finish_reason", None)
                # Reference google.rs:855-856: skip empty and UNSPECIFIED.
                finish_reason_str = ""
                if finish_reason is not None:
                    finish_reason_str = (
                        getattr(finish_reason, "name", None) or str(finish_reason)
                    ).strip()
                if finish_reason_str and finish_reason_str != "FINISH_REASON_UNSPECIFIED":
                    stop_reason = self._map_finish_reason(finish_reason)
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

        yield Usage(
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cache_read_input_tokens=cached_tokens,
        )
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
