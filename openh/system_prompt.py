"""Runtime system prompt assembly.

Keeps the user-editable/base prompt separate from dynamic session context
such as environment details and project memory.
"""
from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from . import memdir
from .memory import load_memory

SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"


def merge_base_prompt(default_prompt: str, custom_prompt: str) -> str:
    """Preserve the built-in scaffold and append custom instructions."""
    default_text = (default_prompt or "").strip()
    custom_text = (custom_prompt or "").strip()

    if not default_text:
        return custom_text
    if not custom_text or custom_text == default_text:
        return default_text

    return (
        default_text
        + "\n\n<custom_instructions>\n"
        + custom_text
        + "\n</custom_instructions>"
    )


def build_runtime_system_prompt(
    base_prompt: str,
    cwd: str,
    date_str: str,
) -> str:
    """Combine the editable base prompt with dynamic runtime context."""
    parts: list[str] = []
    base = (base_prompt or "").strip()
    if base:
        parts.append(base)

    parts.append(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)

    env_info = build_env_info_section(cwd, date_str)
    if env_info:
        parts.append(env_info)

    if cwd:
        parts.append(f"<working_directory>{cwd}</working_directory>")

    memory_block = build_memory_section(cwd)
    if memory_block:
        parts.append(memory_block)

    return "\n\n".join(part for part in parts if part.strip())


def build_managed_agent_prompt(
    *,
    executor_model: str,
    executor_max_turns: int,
    max_concurrent: int,
    executor_isolation: bool,
    total_budget_usd: float | None = None,
) -> str:
    isolation_note = (
        "Each executor runs in an isolated git worktree."
        if executor_isolation
        else "Executors share the working directory."
    )
    if total_budget_usd is None:
        budget_note = "No hard budget cap set. Be cost-conscious."
    else:
        budget_note = f"Total session budget: ${total_budget_usd:.2f}. Monitor your spend carefully."

    return f"""
## Managed Agent Mode

You are the MANAGER in a manager-executor architecture.

### Your Role
- You are the planning and reasoning layer. You coordinate work but do NOT execute tasks directly yourself using file/bash tools.
- Delegate implementation work to executor agents using the Agent tool.
- Each executor uses model `{executor_model}` and has up to {executor_max_turns} turns.
- You may run up to {max_concurrent} executors in parallel by setting `run_in_background: true` on the Agent tool call.

### Workflow
1. Analyze the user's request and break it into well-scoped sub-tasks.
2. Spawn an executor agent for each sub-task using the Agent tool.
3. Review executor results. If a result is insufficient, spawn a follow-up executor with clarified instructions.
4. Synthesize all results into a coherent response.

### Writing Good Executor Prompts
- Prompts must be fully self-contained — executors cannot see your conversation history.
- Include all relevant context: file paths, constraints, and what has already been done.
- Be specific about the expected output format.
- Prefer fewer, larger tasks over many tiny ones to save cost.

### Executor Configuration
- Model: `{executor_model}`
- Max turns per executor: {executor_max_turns}
- Max concurrent: {max_concurrent}
- {isolation_note}

### Budget
- {budget_note}
- Prefer batching work into fewer, well-scoped executors over spawning many small ones.
""".strip()


def build_env_info_section(cwd: str, date_str: str) -> str:
    shell = os.environ.get("SHELL") or os.environ.get("COMSPEC") or "unknown"
    shell_name = Path(shell).name if shell else "unknown"

    system_name = platform.system().lower()
    if system_name == "darwin":
        platform_name = "darwin"
    elif system_name == "windows":
        platform_name = "win32"
    else:
        platform_name = "linux"

    os_version = _os_version_string()
    git_state = "Yes" if _is_git_repo(cwd) else "No"

    lines = [
        "<env>",
        f"Working directory: {cwd}",
        f"Is directory a git repo: {git_state}",
        f"Platform: {platform_name}",
        f"OS Version: {os_version}",
        f"Shell: {shell_name}",
        f"Date: {date_str}",
        "</env>",
    ]
    return "\n".join(lines)


def build_memory_section(cwd: str) -> str:
    parts: list[str] = []

    project_memory = load_memory(cwd).strip()
    if project_memory:
        parts.append(project_memory)

    try:
        memdir_block = memdir.build_context_block(cwd).strip()
    except Exception:
        memdir_block = ""
    if memdir_block:
        parts.append(memdir_block)

    if not parts:
        return ""

    return "<memory>\n" + "\n\n---\n\n".join(parts) + "\n</memory>"


def _is_git_repo(cwd: str) -> bool:
    if not cwd:
        return False
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return False
    return proc.returncode == 0 and proc.stdout.strip() == "true"


def _os_version_string() -> str:
    try:
        if platform.system() == "Windows":
            return platform.platform()

        proc = subprocess.run(
            ["uname", "-s", "-r"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return platform.platform()
