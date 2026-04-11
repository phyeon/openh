"""Shared token pricing helpers."""
from __future__ import annotations

MODEL_PRICING_USD_PER_MILLION: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-opus-4-6": (15.0, 75.0),
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
    "claude-haiku-4": (0.80, 4.0),
    # Gemini
    "gemini-3.1-pro-preview": (1.25, 10.0),
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-exp": (0.0, 0.0),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = MODEL_PRICING_USD_PER_MILLION.get(model, (3.0, 15.0))
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
