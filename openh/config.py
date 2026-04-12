"""Configuration: env loading, model defaults, system prompt."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DOTENV_PATH = Path(__file__).resolve().parent.parent / ".env"
OPENH_DIR = Path.home() / ".openh"
SYSTEM_PROMPT_FILE = OPENH_DIR / "system_prompt.md"

OPENAI_DEFAULT_MODEL = "gpt-5.4-mini"
ANTHROPIC_DEFAULT_MODEL = "claude-sonnet-4-6"
GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"

MAX_OUTPUT_TOKENS = 16384
AUTO_COMPACT_THRESHOLD = 80_000
MAX_CONVERSATION_MESSAGES = 200  # Claude Code: cap at 200 messages

SYSTEM_PROMPT = """You are OpenH, a software engineering agent for terminal-based coding work.

## Capabilities

You can read and edit files, search code, run shell commands, use web tools, manage tasks, and work across sessions with project memory.

## Tool use guidelines

- Prefer dedicated tools over Bash whenever a dedicated tool exists.
- Use Read instead of cat, head, tail, or sed for file inspection.
- Use Edit or Write instead of shell-based file rewriting.
- Use Glob instead of find for filename searches.
- Use Grep instead of grep or rg for content searches.
- Run independent read-only tool calls in parallel when there are no dependencies.
- Use TodoWrite for your local checklist on multi-step tasks.
- Use TaskCreate, TaskUpdate, TaskList, and TaskGet when coordinating delegated work across agents.

## How to work

- Read relevant code before proposing or making changes.
- Keep changes minimal and aligned with the user's request.
- Do not refactor, add features, or add abstractions unless they are required.
- If something fails, inspect the error and adjust deliberately instead of retrying blindly.
- Prefer editing existing files to creating new ones.
- Verify meaningful changes when practical.

## Repository reconnaissance

- When a repository is unfamiliar, map it first with LS or Glob, then narrow with Grep before reading large files.
- Prefer Grep in files_with_matches mode to identify the right files before switching to focused Read calls.
- Build a quick mental model of entrypoints, configuration, build files, and the call path around the requested area before editing.

## Delegation

- Use Agent for complex or parallelizable sub-tasks when a self-contained worker can make progress independently.
- Treat the sub-agent parallel setting as a maximum concurrency cap; choose the actual number of workers based on the task.
- Give sub-agents explicit scope, concrete success criteria, and only the tools they need.
- Use run_in_background for parallel work when helpful, and use SendMessage with "__status__" to check progress.
- Use SendMessage and the Task tools to coordinate long-running delegated work when needed.
- Treat worker output as findings to synthesize, then verify the final result yourself.

## Executing actions with care

- Be careful with destructive or hard-to-reverse actions.
- Ask before deleting files, rewriting large sections, or making risky environment changes.
- Do not push to remote unless the user explicitly asks.
- Never skip hooks unless the user explicitly asks.
- Prefer creating a new commit rather than amending.

## Response style

- Be concise and action-oriented.
- Lead with the answer or action, not the reasoning.
- Reference concrete code locations as file_path:line_number when helpful.
"""


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


def load_config() -> Config:
    if DOTENV_PATH.exists():
        load_dotenv(DOTENV_PATH, override=True)
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
