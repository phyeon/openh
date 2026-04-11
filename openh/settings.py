"""Persisted user settings at ~/.openh/settings.json.

Distinct from `config.py` (which reads environment + .env); this module holds
user-editable preferences that survive across sessions.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

SETTINGS_PATH = Path.home() / ".openh" / "settings.json"

ANTHROPIC_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-opus-4",
    "claude-sonnet-4",
    "claude-haiku-4",
]

GEMINI_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-exp",
]


@dataclass
class Settings:
    active_provider: str = "anthropic"
    anthropic_model: str = "claude-sonnet-4-6"
    gemini_model: str = "gemini-2.5-flash"
    max_output_tokens: int = 8192
    auto_compact_threshold: int = 80_000
    subagent_parallel: int = 1
    active_prompt: str = "default"       # preset name
    theme_mode: str = "dark"             # "dark" | "light"
    color_preset: str = "Charcoal"
    font_preset: str = "System (Sans)"
    sidebar_width: int = 280
    window_width: int = 1080
    window_height: int = 820
    skip_permissions: bool = False
    last_session_id: str = ""
    last_session_cwd: str = ""


def load_settings() -> Settings:
    if not SETTINGS_PATH.exists():
        return Settings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return Settings()
    s = Settings()
    for k, v in data.items():
        if hasattr(s, k):
            try:
                setattr(s, k, v)
            except Exception:
                pass
    return s


def save_settings(s: Settings) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(asdict(s), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
