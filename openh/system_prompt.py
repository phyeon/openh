"""Runtime system prompt assembly with static/dynamic section separation."""
from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from . import memdir
from .coordinator import coordinator_system_prompt
from .memory import load_memory

SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"
_SECTION_CACHE: dict[str, str | None] = {}

CORE_CAPABILITIES = """
## Capabilities

You have access to powerful tools for software engineering tasks:
- **Read/Write files**: Read any file, write new files, edit existing files with precise diffs
- **Execute commands**: Run bash commands, PowerShell scripts, background processes
- **Search**: Glob patterns, regex grep, web search, file content search
- **Web**: Fetch URLs, search the internet
- **Agents**: Spawn parallel sub-agents for complex multi-step work
- **Memory**: Persistent notes across sessions via the memory system
- **MCP servers**: Connect to external tools and APIs via Model Context Protocol
- **Jupyter notebooks**: Read and edit notebook cells

## How to approach tasks

1. **Understand before acting**: Read relevant files before making changes
2. **Minimal changes**: Only modify what's needed. Don't refactor unrequested code.
3. **Verify**: Check your work with tests or by reading the result
4. **Communicate blockers**: If stuck, ask the user rather than guessing
""".strip()

TOOL_USE_GUIDELINES = """
## Tool use guidelines

- Use dedicated tools (Read, Edit, Glob, Grep) instead of bash equivalents
- For searches, prefer Grep over `grep`; prefer Glob over `find`
- Parallelize independent tool calls in a single response
- For file edits: always read the file first, then make targeted edits
- Use Sleep instead of `Bash(sleep ...)` for waits or polling delays
- Bash commands timeout after 2 minutes; use background mode for long operations
""".strip()

ACTIONS_SECTION = """
## Executing actions with care

Carefully consider the reversibility and blast radius of actions. For actions
that are hard to reverse, affect shared systems, or could be risky or
destructive, check with the user before proceeding. Authorization stands for
the scope specified, not beyond. Match the scope of your actions to what was
actually requested.
""".strip()

SAFETY_GUIDELINES = """
## Safety guidelines

- Never delete files without explicit user confirmation
- Don't modify protected files (.gitconfig, .bashrc, .zshrc, .mcp.json, .claude.json)
- Be careful with destructive operations (rm -rf, DROP TABLE, etc.)
- Don't commit secrets, credentials, or API keys
- For ambiguous destructive actions, ask before proceeding
""".strip()

CYBER_RISK_INSTRUCTION = """
## Security

You are authorized to assist with security research, CTF challenges, penetration testing
with explicit authorization, defensive security, and educational security content. Do not
assist with creating malware, unauthorized access, denial-of-service attacks, or any
destructive security techniques without clear legitimate purpose.
""".strip()


@dataclass(frozen=True, slots=True)
class SystemPromptSection:
    tag: str
    content: str | None
    cache_break: bool = False


class OutputStyle(str, Enum):
    DEFAULT = "default"
    EXPLANATORY = "explanatory"
    LEARNING = "learning"
    CONCISE = "concise"
    FORMAL = "formal"
    CASUAL = "casual"

    def prompt_suffix(self) -> str | None:
        if self is OutputStyle.EXPLANATORY:
            return (
                "When explaining code or concepts, be thorough and educational. "
                "Include reasoning, alternatives considered, and potential pitfalls. "
                "Err on the side of over-explaining."
            )
        if self is OutputStyle.LEARNING:
            return (
                "This user is learning. Explain concepts as you implement them. "
                "Point out patterns, best practices, and why you made each decision. "
                "Use analogies when helpful."
            )
        if self is OutputStyle.CONCISE:
            return (
                "Be maximally concise. Skip preamble, summaries, and filler. "
                "Lead with the answer. One sentence is better than three."
            )
        if self is OutputStyle.FORMAL:
            return "Maintain a formal, professional tone. Use precise technical language."
        if self is OutputStyle.CASUAL:
            return "Use a casual, conversational tone."
        return None

    @classmethod
    def from_str(cls, value: str | None) -> "OutputStyle":
        raw = str(value or "").strip().lower()
        for item in cls:
            if raw == item.value:
                return item
        return cls.DEFAULT


class SystemPromptPrefix(str, Enum):
    CLI = "cli"
    SDK = "sdk"
    SDK_PRESET = "sdk_preset"
    VERTEX = "vertex"
    BEDROCK = "bedrock"
    REMOTE = "remote"

    @classmethod
    def detect(
        cls,
        *,
        is_non_interactive: bool,
        has_append_system_prompt: bool,
    ) -> "SystemPromptPrefix":
        if os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID") or os.environ.get("CLOUD_ML_PROJECT_ID"):
            return cls.VERTEX
        if os.environ.get("AWS_BEDROCK_MODEL_ID"):
            return cls.BEDROCK
        if os.environ.get("CLAUDE_CODE_REMOTE"):
            return cls.REMOTE
        if is_non_interactive:
            if has_append_system_prompt:
                return cls.SDK_PRESET
            return cls.SDK
        return cls.CLI

    def attribution_text(self) -> str:
        if self in {SystemPromptPrefix.CLI, SystemPromptPrefix.VERTEX, SystemPromptPrefix.BEDROCK, SystemPromptPrefix.REMOTE}:
            return "You are Claude Code, Anthropic's official CLI for Claude."
        if self is SystemPromptPrefix.SDK_PRESET:
            return (
                "You are Claude Code, Anthropic's official CLI for Claude, "
                "running within the Claude Agent SDK."
            )
        return "You are a Claude agent, built on Anthropic's Claude Agent SDK."


@dataclass(slots=True)
class SystemPromptOptions:
    prefix: SystemPromptPrefix | None = None
    is_non_interactive: bool = False
    has_append_system_prompt: bool = False
    output_style: OutputStyle = OutputStyle.DEFAULT
    custom_output_style_prompt: str | None = None
    working_directory: str | None = None
    memory_content: str = ""
    custom_system_prompt: str | None = None
    append_system_prompt: str | None = None
    user_profile: str | None = None
    agent_persona: str | None = None
    custom_prefix: str | None = None  # overrides "You are Claude Code..." attribution
    replace_system_prompt: bool = False
    coordinator_mode: bool = False
    skip_env_info: bool = False


DEFAULT_SYSTEM_PROMPT = "\n\n".join(
    [
        SystemPromptPrefix.CLI.attribution_text(),
        CORE_CAPABILITIES,
        TOOL_USE_GUIDELINES,
        ACTIONS_SECTION,
        SAFETY_GUIDELINES,
        CYBER_RISK_INSTRUCTION,
    ]
).strip()


def clear_system_prompt_sections() -> None:
    _SECTION_CACHE.clear()


def _cached_section(tag: str, content: str | None) -> SystemPromptSection:
    normalized = (content or "").strip() or None
    if normalized is None:
        _SECTION_CACHE[tag] = None
        return SystemPromptSection(tag=tag, content=None, cache_break=False)
    cached = _SECTION_CACHE.get(tag)
    if cached != normalized:
        _SECTION_CACHE[tag] = normalized
    return SystemPromptSection(tag=tag, content=_SECTION_CACHE.get(tag), cache_break=False)


def _dynamic_section(tag: str, content: str | None) -> SystemPromptSection:
    normalized = (content or "").strip() or None
    return SystemPromptSection(tag=tag, content=normalized, cache_break=True)


def merge_base_prompt(default_prompt: str, custom_prompt: str) -> str:
    """Preserve compatibility with the prompt editor and legacy callers."""
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


def build_system_prompt(
    opts: SystemPromptOptions,
    *,
    date_str: str = "",
) -> str:
    custom_system_prompt = (opts.custom_system_prompt or "").strip() or None
    if opts.replace_system_prompt and custom_system_prompt:
        return custom_system_prompt + "\n\n" + SYSTEM_PROMPT_DYNAMIC_BOUNDARY

    prefix = opts.prefix or SystemPromptPrefix.detect(
        is_non_interactive=opts.is_non_interactive,
        has_append_system_prompt=opts.has_append_system_prompt,
    )

    # Custom prefix overrides the default attribution line.
    prefix_text = (
        opts.custom_prefix if hasattr(opts, "custom_prefix") and opts.custom_prefix
        else prefix.attribution_text()
    )

    static_sections: list[SystemPromptSection] = [
        _cached_section(f"prefix:{prefix.value}", prefix_text),
        _cached_section("core_capabilities", CORE_CAPABILITIES),
        _cached_section("tool_use_guidelines", TOOL_USE_GUIDELINES),
        _cached_section("actions_section", ACTIONS_SECTION),
        _cached_section("safety_guidelines", SAFETY_GUIDELINES),
        _cached_section("cyber_risk_instruction", CYBER_RISK_INSTRUCTION),
    ]

    style_text = (
        (opts.custom_output_style_prompt or "").strip()
        or opts.output_style.prompt_suffix()
    )
    if style_text:
        static_sections.append(
            _cached_section("output_style", "## Output Style\n" + style_text)
        )

    if opts.coordinator_mode:
        static_sections.append(
            _cached_section("coordinator_mode", coordinator_system_prompt().strip())
        )

    if custom_system_prompt:
        static_sections.append(
            _cached_section(
                "custom_system_prompt",
                f"<custom_instructions>\n{custom_system_prompt}\n</custom_instructions>",
            )
        )

    dynamic_sections: list[SystemPromptSection] = []
    if not opts.skip_env_info:
        dynamic_sections.append(
            _dynamic_section(
                "env_info",
                build_env_info_section(opts.working_directory, date_str=date_str),
            )
        )
    if opts.working_directory:
        dynamic_sections.append(
            _dynamic_section(
                "working_directory",
                f"<working_directory>{opts.working_directory}</working_directory>",
            )
        )
    if opts.memory_content.strip():
        dynamic_sections.append(
            _dynamic_section(
                "memory",
                f"<memory>\n{opts.memory_content.strip()}\n</memory>",
            )
        )
    user_profile = (opts.user_profile or "").strip()
    if user_profile:
        dynamic_sections.append(
            _dynamic_section(
                "user_profile",
                f"<user_profile>\n{user_profile}\n</user_profile>",
            )
        )
    agent_persona = (opts.agent_persona or "").strip()
    if agent_persona:
        dynamic_sections.append(
            _dynamic_section(
                "agent_persona",
                f"<agent_persona>\n{agent_persona}\n</agent_persona>",
            )
        )
    append_system_prompt = (opts.append_system_prompt or "").strip()
    if append_system_prompt:
        dynamic_sections.append(
            _dynamic_section("append_system_prompt", append_system_prompt)
        )

    parts = [section.content for section in static_sections if section.content]
    parts.append(SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
    parts.extend(section.content for section in dynamic_sections if section.content)
    return "\n\n".join(part for part in parts if part and part.strip())


def build_runtime_system_prompt(
    default_prompt: str,
    cwd: str,
    date_str: str,
    *,
    custom_prompt: str = "",
    append_system_prompt: str = "",
    managed_prompt: str = "",
    replace_system_prompt: bool = False,
    skip_env_info: bool = False,
    output_style: str | OutputStyle = OutputStyle.DEFAULT,
    custom_output_style_prompt: str = "",
    is_non_interactive: bool = False,
    prefix: str | SystemPromptPrefix | None = None,
    custom_prefix: str = "",
    coordinator_mode: bool = False,
    user_profile: str = "",
    agent_persona: str = "",
) -> str:
    """Compatibility wrapper around the PB/fresh-style prompt builder."""
    loaded_prompt = (default_prompt or "").strip()
    custom_parts: list[str] = []
    if loaded_prompt and loaded_prompt != DEFAULT_SYSTEM_PROMPT:
        custom_parts.append(loaded_prompt)
    if managed_prompt.strip():
        custom_parts.append(managed_prompt.strip())
    if custom_prompt.strip():
        custom_parts.append(custom_prompt.strip())

    style = output_style if isinstance(output_style, OutputStyle) else OutputStyle.from_str(output_style)
    system_prefix: SystemPromptPrefix | None
    if isinstance(prefix, SystemPromptPrefix):
        system_prefix = prefix
    elif prefix:
        try:
            system_prefix = SystemPromptPrefix(str(prefix))
        except ValueError:
            system_prefix = None
    else:
        system_prefix = None

    opts = SystemPromptOptions(
        prefix=system_prefix,
        is_non_interactive=is_non_interactive,
        has_append_system_prompt=bool((append_system_prompt or "").strip()),
        output_style=style,
        custom_output_style_prompt=(custom_output_style_prompt or "").strip() or None,
        working_directory=(cwd or "").strip() or None,
        memory_content=build_memory_content(cwd),
        custom_system_prompt="\n\n".join(part for part in custom_parts if part) or None,
        append_system_prompt=(append_system_prompt or "").strip() or None,
        user_profile=(user_profile or "").strip() or None,
        agent_persona=(agent_persona or "").strip() or None,
        custom_prefix=(custom_prefix or "").strip() or None,
        replace_system_prompt=replace_system_prompt,
        coordinator_mode=coordinator_mode,
        skip_env_info=skip_env_info,
    )
    return build_system_prompt(opts, date_str=date_str)


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


def build_env_info_section(working_dir: str | None, *, date_str: str = "") -> str:
    del date_str  # fresh/PB builder does not inject a separate date line here

    system_name = platform.system().lower()
    if system_name == "windows":
        platform_name = "win32"
    elif system_name == "darwin":
        platform_name = "darwin"
    else:
        platform_name = "linux"

    os_version = _os_version_string(platform_name)
    shell_env = os.environ.get("SHELL", "")
    if "zsh" in shell_env:
        shell_name = "zsh"
    elif "bash" in shell_env:
        shell_name = "bash"
    elif "fish" in shell_env:
        shell_name = "fish"
    elif platform_name == "win32":
        shell_name = "powershell"
    elif not shell_env:
        shell_name = "unknown"
    else:
        shell_name = shell_env

    if platform_name == "win32":
        shell_line = (
            "Shell: "
            + shell_name
            + " (use Unix shell syntax, not Windows — e.g., /dev/null not NUL, forward slashes in paths)"
        )
    else:
        shell_line = f"Shell: {shell_name}"

    is_git = False
    if working_dir:
        try:
            is_git = Path(working_dir).joinpath(".git").exists()
        except Exception:
            is_git = False

    cwd_line = f"\nWorking directory: {working_dir}" if working_dir else ""
    if platform_name == "win32":
        os_note = (
            "\nIMPORTANT: The user is on Windows ("
            + os_version
            + "). Use Windows-compatible commands (e.g., `dir` not `ls`, `type` not `cat`, backslashes in native paths). "
              "When the shell is bash/git-bash, Unix syntax is acceptable."
        )
    elif platform_name == "darwin":
        os_note = (
            "\nThe user is on macOS ("
            + os_version
            + "). Use macOS-compatible commands. BSD variants of tools apply (e.g., `sed -i ''` not `sed -i`)."
        )
    else:
        os_note = f"\nThe user is on Linux ({os_version}). Use Linux-compatible commands."

    return (
        f"<env>{cwd_line}\n"
        f"Is directory a git repo: {'Yes' if is_git else 'No'}\n"
        f"Platform: {platform_name}\n"
        f"OS Version: {os_version}\n"
        f"{shell_line}"
        f"{os_note}\n"
        "</env>"
    )


def build_memory_content(cwd: str) -> str:
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

    return "\n\n---\n\n".join(parts).strip()


def _os_version_string(platform_name: str) -> str:
    try:
        if platform_name == "win32":
            proc = subprocess.run(
                ["cmd", "/c", "ver"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            ver = proc.stdout.strip()
            arch = os.environ.get("PROCESSOR_ARCHITECTURE", "").strip()
            if ver:
                return f"{ver} ({arch})" if arch else ver
            return f"Windows ({arch})" if arch else "Windows"

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
