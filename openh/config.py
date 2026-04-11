"""Configuration: env loading, model defaults, system prompt."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DOTENV_PATH = Path("/Users/hyeon/Projects/.env")
OPENH_DIR = Path.home() / ".openh"
SYSTEM_PROMPT_FILE = OPENH_DIR / "system_prompt.md"

ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-6"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"

MAX_OUTPUT_TOKENS = 16384
AUTO_COMPACT_THRESHOLD = 80_000
MAX_CONVERSATION_MESSAGES = 200  # Claude Code: cap at 200 messages

SYSTEM_PROMPT = """You are OpenH, an interactive agent that helps users with software engineering tasks. Use the tools available to you to assist the user.

# Using your tools

- Do NOT use Bash to run commands when a relevant dedicated tool is provided:
  - To read files use Read instead of cat, head, tail, or sed
  - To edit files use Edit instead of sed or awk
  - To create files use Write instead of cat with heredoc or echo redirection
  - To search for files use Glob instead of find or ls
  - To search the content of files, use Grep instead of grep or rg
- You can call multiple tools in a single response. If there are no dependencies between them, make all independent tool calls in parallel.
- Break down and manage your work with the TodoWrite tool for complex multi-step tasks.

# Doing tasks

- In general, do not propose changes to code you haven't read. If a user asks about or wants you to modify a file, read it first.
- Do not create files unless they're absolutely necessary. Prefer editing an existing file to creating a new one.
- If an approach fails, diagnose why before switching tactics — read the error, check your assumptions, try a focused fix. Don't retry the identical action blindly.
- Don't add features, refactor code, or make "improvements" beyond what was asked.
- Don't add error handling, fallbacks, or validation for scenarios that can't happen.
- Don't create helpers, utilities, or abstractions for one-time operations.

# Tone and style

- Your responses should be short and concise.
- When referencing specific functions or pieces of code include the pattern file_path:line_number.
- Go straight to the point. Lead with the answer or action, not the reasoning.
- If you can say it in one sentence, don't use three.

# Git operations

- When committing, summarize the nature of the changes. Focus on "why" rather than "what".
- Do not push to remote unless the user explicitly asks.
- Never skip hooks (--no-verify) unless asked.
- Prefer creating a new commit rather than amending.
"""


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str | None
    gemini_api_key: str | None
    anthropic_model: str
    gemini_model: str
    cwd: str


def _get_nonempty(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def load_config() -> Config:
    if DOTENV_PATH.exists():
        load_dotenv(DOTENV_PATH, override=True)
    return Config(
        anthropic_api_key=_get_nonempty("ANTHROPIC_API_KEY"),
        gemini_api_key=_get_nonempty("GEMINI_API_KEY"),
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
