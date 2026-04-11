"""Shared token pricing helpers."""
from __future__ import annotations

MODEL_PRICING_USD_PER_MILLION: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-5.4": (2.50, 15.0),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4-nano": (0.20, 1.25),
    # Anthropic
    "claude-opus-4-6": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
    # Gemini
    "gemini-3.1-pro-preview": (2.0, 12.0),
    "gemini-3-flash-preview": (0.50, 3.0),
    "gemini-2.5-flash": (0.15, 0.60),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = MODEL_PRICING_USD_PER_MILLION.get(model, (3.0, 15.0))
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
