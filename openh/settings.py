"""Persisted user settings at ~/.openh/settings.json.

Distinct from `config.py` (which reads environment + .env); this module holds
user-editable preferences that survive across sessions.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

SETTINGS_PATH = Path.home() / ".openh" / "settings.json"

OPENAI_MODELS = [
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
]

ANTHROPIC_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

GEMINI_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
]
GEMINI_THINKING_EFFORTS = [
    "low",
    "medium",
    "high",
    "max",
]

_PROVIDERS = {"openai", "anthropic", "gemini"}
_KNOWN_KEYS = {
    "active_provider",
    "openai_model",
    "anthropic_model",
    "gemini_model",
    "gemini_thinking_effort",
    "output_style",
    "max_output_tokens",
    "auto_compact_threshold",
    "subagent_parallel",
    "active_prompt",
    "theme_mode",
    "color_preset",
    "font_preset",
    "font_size",
    "user_profile_enabled",
    "user_profile_text",
    "agent_persona_enabled",
    "agent_persona_text",
    "sidebar_width",
    "window_width",
    "window_height",
    "skip_permissions",
    "last_session_id",
    "last_session_cwd",
}


@dataclass
class Settings:
    active_provider: str = "anthropic"
    openai_model: str = "gpt-5.4-mini"
    anthropic_model: str = "claude-sonnet-4-6"
    gemini_model: str = "gemini-2.5-flash"
    gemini_thinking_effort: str = "low"
    output_style: str = "default"
    max_output_tokens: int = 8192
    auto_compact_threshold: int = 80_000
    subagent_parallel: int = 1
    active_prompt: str = "default"
    theme_mode: str = "dark"
    color_preset: str = "Charcoal"
    font_preset: str = "System (Sans)"
    font_size: int = 16
    user_profile_enabled: bool = False
    user_profile_text: str = ""
    agent_persona_enabled: bool = False
    agent_persona_text: str = ""
    sidebar_width: int = 280
    window_width: int = 1080
    window_height: int = 820
    skip_permissions: bool = False
    last_session_id: str = ""
    last_session_cwd: str = ""


def _coerce_str(value: object, default: str) -> str:
    if isinstance(value, str):
        value = value.strip()
        return value or default
    return default


def _coerce_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value: object, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    if minimum is not None and parsed < minimum:
        parsed = minimum
    if maximum is not None and parsed > maximum:
        parsed = maximum
    return parsed


def normalize_settings(s: Settings) -> Settings:
    s.active_provider = _coerce_str(s.active_provider, "anthropic").lower()
    if s.active_provider not in _PROVIDERS:
        s.active_provider = "anthropic"

    s.openai_model = _coerce_str(s.openai_model, "gpt-5.4-mini")
    s.anthropic_model = _coerce_str(s.anthropic_model, "claude-sonnet-4-6")
    s.gemini_model = _coerce_str(s.gemini_model, "gemini-2.5-flash")
    gemini_effort = _coerce_str(s.gemini_thinking_effort, "low").lower()
    s.gemini_thinking_effort = (
        gemini_effort if gemini_effort in set(GEMINI_THINKING_EFFORTS) else "low"
    )
    s.output_style = _coerce_str(s.output_style, "default").lower()
    s.active_prompt = _coerce_str(s.active_prompt, "default")

    theme_mode = _coerce_str(s.theme_mode, "dark").lower()
    s.theme_mode = theme_mode if theme_mode in {"dark", "light"} else "dark"
    s.color_preset = _coerce_str(s.color_preset, "Charcoal")
    s.font_preset = _coerce_str(s.font_preset, "System (Sans)")
    s.user_profile_enabled = _coerce_bool(s.user_profile_enabled, False)
    s.user_profile_text = _coerce_str(s.user_profile_text, "")
    s.agent_persona_enabled = _coerce_bool(s.agent_persona_enabled, False)
    s.agent_persona_text = _coerce_str(s.agent_persona_text, "")

    s.max_output_tokens = _coerce_int(s.max_output_tokens, 8192, minimum=256)
    s.auto_compact_threshold = _coerce_int(s.auto_compact_threshold, 80_000, minimum=0)
    s.subagent_parallel = _coerce_int(s.subagent_parallel, 1, minimum=1, maximum=8)
    s.font_size = _coerce_int(s.font_size, 16, minimum=12, maximum=24)
    s.sidebar_width = _coerce_int(s.sidebar_width, 280, minimum=220, maximum=520)
    s.window_width = _coerce_int(s.window_width, 1080, minimum=900, maximum=2560)
    s.window_height = _coerce_int(s.window_height, 820, minimum=640, maximum=1800)

    s.skip_permissions = _coerce_bool(s.skip_permissions, False)
    s.last_session_id = _coerce_str(s.last_session_id, "")
    s.last_session_cwd = _coerce_str(s.last_session_cwd, "")
    return s


def load_settings() -> Settings:
    if not SETTINGS_PATH.exists():
        return Settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return Settings()
    if not isinstance(data, dict):
        return Settings()

    s = Settings()
    for key in _KNOWN_KEYS:
        if key in data:
            try:
                setattr(s, key, data[key])
            except Exception:
                pass
    return normalize_settings(s)


def save_settings(s: Settings) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)

    raw: dict[str, object] = {}
    if SETTINGS_PATH.exists():
        try:
            current = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(current, dict):
                raw = current
        except Exception:
            raw = {}

    payload = asdict(normalize_settings(s))
    raw.update(payload)
    SETTINGS_PATH.write_text(
        json.dumps(raw, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
