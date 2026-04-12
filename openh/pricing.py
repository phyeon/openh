"""Shared token pricing helpers."""
from __future__ import annotations

MODEL_PRICING_USD_PER_MILLION: dict[str, tuple[float, float, float, float]] = {
    # OpenAI
    "gpt-5.4": (2.50, 15.0, 0.0, 0.0),
    "gpt-5.4-mini": (0.75, 4.50, 0.0, 0.0),
    "gpt-5.4-nano": (0.20, 1.25, 0.0, 0.0),
    # Anthropic (2026-04 기준)
    "claude-opus-4-6": (15.0, 75.0, 18.75, 1.5),
    "claude-sonnet-4-6": (3.0, 15.0, 3.75, 0.3),
    "claude-haiku-4-5": (0.8, 4.0, 1.0, 0.08),
    # Gemini (2026-04 기준)
    "gemini-3.1-pro-preview": (2.0, 12.0, 0.0, 0.0),
    "gemini-3-flash-preview": (0.50, 3.0, 0.0, 0.0),
    "gemini-2.5-flash": (0.15, 0.60, 0.0, 0.0),
}


def estimate_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> float:
    in_price, out_price, cache_create_price, cache_read_price = (
        MODEL_PRICING_USD_PER_MILLION.get(model, (3.0, 15.0, 0.0, 0.0))
    )
    return (
        input_tokens * in_price
        + output_tokens * out_price
        + cache_creation_input_tokens * cache_create_price
        + cache_read_input_tokens * cache_read_price
    ) / 1_000_000
