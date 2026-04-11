"""Provider registry."""
from __future__ import annotations

from typing import Callable

from ..config import Config
from .anthropic import AnthropicProvider
from .base import Provider, ToolSchema

__all__ = ["Provider", "ToolSchema", "get_provider", "PROVIDER_NAMES"]

PROVIDER_NAMES = ("openai", "anthropic", "gemini")


def get_provider(name: str, config: Config) -> Provider:
    if name == "openai":
        try:
            from .openai import OpenAIProvider
        except ModuleNotFoundError as exc:
            raise RuntimeError("OpenAI SDK not installed. Reinstall dependencies first.") from exc

        if not config.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY not set")
        return OpenAIProvider(api_key=config.openai_api_key, model=config.openai_model)
    if name == "anthropic":
        if not config.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        return AnthropicProvider(api_key=config.anthropic_api_key, model=config.anthropic_model)
    if name == "gemini":
        # Imported lazily so Phase 1 doesn't depend on google-genai being installed.
        from .gemini import GeminiProvider

        if not config.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        return GeminiProvider(api_key=config.gemini_api_key, model=config.gemini_model)
    raise ValueError(f"unknown provider: {name}")
