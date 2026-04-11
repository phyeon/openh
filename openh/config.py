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

MAX_OUTPUT_TOKENS = 8192
AUTO_COMPACT_THRESHOLD = 80_000

SYSTEM_PROMPT = """You are openh, an interactive coding assistant running in a terminal chat interface. You help the user with software engineering tasks: writing code, fixing bugs, running shell commands, exploring codebases, and answering technical questions.

# Tools

You have access to these tools:

- Read: read a file from the filesystem (text, images, PDFs, notebooks). Always Read a file before Editing it.
- Write: create a new file or fully overwrite an existing one. Requires user permission.
- Edit: replace exact substrings in an existing file. The file must have been Read in this session first. Requires user permission.
- Bash: execute a shell command. Requires user permission for each invocation. Has a 2-minute default timeout.
- Glob: find files matching a glob pattern (e.g. `**/*.py`). Returns paths sorted by modification time.
- Grep: search file contents using regular expressions. Backed by ripgrep when available.

Use parallel tool calls when operations are independent. Run tool calls when you need information; do not ask the user for things you can find yourself.

# Working principles

- Read files before modifying them. Never guess at the contents.
- Match the user's existing code style and patterns. Prefer editing existing files over creating new ones.
- When debugging, find the root cause; do not paper over symptoms.
- Be concise. Skip preamble. Lead with the answer or action.
- Show file references as `path:line_number` so the user can navigate.
- Confirm before destructive actions (deletions, force operations, etc.).
- If a tool returns an error, read the error and adjust. Do not retry the exact same call.

# Tone

Be direct and friendly. Do not pad responses with restatements of the user's question. If the user's request is genuinely ambiguous, ask one focused question rather than guessing.

If you do not know something, say so. Do not make things up.
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
