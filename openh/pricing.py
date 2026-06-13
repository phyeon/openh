"""Shared token pricing helpers."""
from __future__ import annotations

# (input_price, output_price, cache_create_price, cache_read_price) per 1M tokens
MODEL_PRICING_USD_PER_MILLION: dict[str, tuple[float, float, float, float]] = {
    # OpenAI — cache_read = 50-75% off input (automatic caching)
    "gpt-5.4": (2.50, 15.0, 0.0, 0.625),       # 75% off
    "gpt-5.4-mini": (0.75, 4.50, 0.0, 0.1875),  # 75% off
    "gpt-5.4-nano": (0.20, 1.25, 0.0, 0.05),    # 75% off
    # Anthropic (2026-04 기준)
    "claude-opus-4-6": (15.0, 75.0, 18.75, 1.5),
    "claude-sonnet-4-6": (3.0, 15.0, 3.75, 0.3),
    "claude-haiku-4-5": (0.8, 4.0, 1.0, 0.08),
    # Gemini — cache_read = 67-90% off input (implicit caching)
    "gemini-3.5-flash": (1.50, 9.0, 0.0, 0.15),         # 90% off  (GA 2026-05-19)
    "gemini-3.1-pro-preview": (2.0, 12.0, 0.0, 0.20),   # 90% off
    "gemini-3.1-flash-lite-preview": (0.25, 1.50, 0.0, 0.025),  # 90% off
    "gemini-3-flash-preview": (0.50, 3.0, 0.0, 0.05),    # 90% off  (note: free tier)
    "gemini-2.5-flash": (0.15, 0.60, 0.0, 0.03),         # 80% off
    "gemini-2.5-pro": (1.25, 10.0, 0.0, 0.125),          # 90% off
    # DeepSeek — standard rate (post-promo, 2026-06).  cache_read ≈ 1/10 input.
    "deepseek-v4-pro": (1.74, 3.48, 0.0, 0.0145),
    "deepseek-v4-flash": (0.28, 0.42, 0.0, 0.028),       # approx — verify on deepseek.ai/pricing
    # Moonshot / Kimi — cache_hit ≈ 1/6 input
    "kimi-k2.6": (0.95, 4.00, 0.0, 0.16),
    "kimi-k2.7-code": (0.95, 4.00, 0.0, 0.16),           # approx — verify on platform.moonshot.ai
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
    # Cached tokens are already counted in input_tokens by providers.
    # Subtract them to avoid double-charging, then charge at cache rate.
    non_cached_input = max(0, input_tokens - cache_read_input_tokens)
    return (
        non_cached_input * in_price
        + output_tokens * out_price
        + cache_creation_input_tokens * cache_create_price
        + cache_read_input_tokens * cache_read_price
    ) / 1_000_000
