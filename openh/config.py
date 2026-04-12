"""Configuration: env loading, model defaults, system prompt."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from .system_prompt import DEFAULT_SYSTEM_PROMPT

OPENH_DIR = Path.home() / ".openh"
REPO_DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
USER_DOTENV_PATH = OPENH_DIR / ".env"
DOTENV_PATH = REPO_DOTENV_PATH
SYSTEM_PROMPT_FILE = OPENH_DIR / "system_prompt.md"

OPENAI_DEFAULT_MODEL = "gpt-5.4-mini"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-6"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"

MAX_OUTPUT_TOKENS = 16384
AUTO_COMPACT_THRESHOLD = 80_000
MAX_CONVERSATION_MESSAGES = 200  # Claude Code: cap at 200 messages

SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT


@dataclass(frozen=True)
class Config:
    openai_api_key: str | None
    anthropic_api_key: str | None
    gemini_api_key: str | None
    openai_model: str
    anthropic_model: str
    gemini_model: str
    cwd: str


def _get_nonempty(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def dotenv_paths() -> tuple[Path, ...]:
    ordered: list[Path] = []
    for path in (USER_DOTENV_PATH, REPO_DOTENV_PATH):
        if path not in ordered:
            ordered.append(path)
    return tuple(ordered)


def load_env_files() -> tuple[Path, ...]:
    loaded: list[Path] = []
    for path in dotenv_paths():
        if not path.exists():
            continue
        load_dotenv(path, override=True)
        loaded.append(path)
    return tuple(loaded)


def load_config() -> Config:
    load_env_files()
    return Config(
        openai_api_key=_get_nonempty("OPENAI_API_KEY"),
        anthropic_api_key=_get_nonempty("ANTHROPIC_API_KEY"),
        gemini_api_key=_get_nonempty("GEMINI_API_KEY"),
        openai_model=os.environ.get("OPENH_OPENAI_MODEL") or OPENAI_DEFAULT_MODEL,
        anthropic_model=os.environ.get("OPENH_ANTHROPIC_MODEL") or ANTHROPIC_DEFAULT_MODEL,
        gemini_model=os.environ.get("OPENH_GEMINI_MODEL") or GEMINI_DEFAULT_MODEL,
        cwd=os.getcwd(),
    )


def load_system_prompt() -> str:
    """Return the effective system prompt.

    Resolution order (first match wins):
      1. OPENH_SYSTEM_PROMPT environment variable
      2. ~/.openh/system_prompt.md file
      3. Built-in default (SYSTEM_PROMPT constant)
    """
    override = os.environ.get("OPENH_SYSTEM_PROMPT")
    if override and override.strip():
        return override
    if SYSTEM_PROMPT_FILE.exists():
        try:
            content = SYSTEM_PROMPT_FILE.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError:
            pass
    return SYSTEM_PROMPT
