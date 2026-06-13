"""Moonshot (Kimi) provider.

Moonshot's API is OpenAI-compatible (Chat Completions, streaming, tools,
tool_choice, temperature/top_p/max_tokens), so this is a thin subclass of
:class:`OpenAIProvider` pointed at Moonshot's ``base_url``.

Models: ``kimi-k2.6`` (proven top open-weight) and ``kimi-k2.7-code``
(coding-specialized, released 2026-06-12). Both support function calling.

Note: the international endpoint is ``api.moonshot.ai``; mainland China uses
``api.moonshot.cn``. We use the ``.ai`` endpoint.
"""
from __future__ import annotations

from .openai import OpenAIProvider

MOONSHOT_BASE_URL = "https://api.moonshot.ai/v1"


class MoonshotProvider(OpenAIProvider):
    name: str = "moonshot"

    def __init__(self, api_key: str, model: str) -> None:
        super().__init__(api_key=api_key, model=model, base_url=MOONSHOT_BASE_URL)
