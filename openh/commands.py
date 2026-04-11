"""Slash command dispatcher.

Commands intercept user input before it reaches the model. Each command gets
a Context object (session, ui hooks) and returns a CommandResult.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from .session import AgentSession


@dataclass
class CommandResult:
    handled: bool
    output: str = ""          # Text to display as a system note (if any)
    clear_log: bool = False   # Whether the UI should clear the log
    refresh_status: bool = False
    quit: bool = False


@dataclass
class CommandContext:
    session: "AgentSession"
    on_clear: Callable[[], None]
    on_switch_model: Callable[[str], None]  # arg: provider name
    on_toggle_theme: Callable[[], None]
    on_compact_now: Callable[[], None]
    on_init: Callable[[], None]
    set_title: Callable[[str], None]


class CommandDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[list[str], CommandContext], CommandResult]] = {}
        self._help_lines: list[tuple[str, str]] = []
        self._register_builtins()

    def register(
        self,
        name: str,
        handler: Callable[[list[str], CommandContext], CommandResult],
        help_text: str,
    ) -> None:
        self._handlers[name] = handler
        self._help_lines.append((name, help_text))

    def dispatch(self, text: str, ctx: CommandContext) -> Optional[CommandResult]:
        if not text.startswith("/"):
            return None
        parts = text[1:].split()
        if not parts:
            return None
        cmd = parts[0].lower()
        args = parts[1:]
        handler = self._handlers.get(cmd)
        if handler is None:
            return CommandResult(handled=True, output=f"unknown command: /{cmd}")
        return handler(args, ctx)

    def _register_builtins(self) -> None:
        self.register("help", _cmd_help(self), "Show available slash commands")
        self.register("clear", _cmd_clear, "Clear the current conversation")
        self.register("new", _cmd_clear, "Alias for /clear")
        self.register("model", _cmd_model, "Switch model: /model anthropic | gemini")
        self.register("switch", _cmd_model, "Alias for /model")
        self.register("tokens", _cmd_tokens, "Show current token usage")
        self.register("status", _cmd_status, "Show session status")
        self.register("compact", _cmd_compact, "Force summarize + compact the conversation")
        self.register("rename", _cmd_rename, "Rename the current conversation: /rename new title")
        self.register("theme", _cmd_theme, "Toggle light/dark theme")
        self.register("init", _cmd_init, "Generate a starter CLAUDE.md in the current directory")
        self.register("memory", _cmd_memory, "Show loaded CLAUDE.md memory")
        self.register("todos", _cmd_todos, "Show the current todo list")
        self.register("cwd", _cmd_cwd, "Show the current working directory")
        self.register("version", _cmd_version, "Show openh version")
        self.register("tools", _cmd_tools, "List available tools")
        self.register("providers", _cmd_providers, "List available model providers")
        self.register("system", _cmd_system, "Show the active system prompt")
        self.register("config", _cmd_config, "Show effective configuration (env + files)")


def _cmd_help(dispatcher: "CommandDispatcher"):
    def handler(args: list[str], ctx: CommandContext) -> CommandResult:
        lines = ["# Slash commands", ""]
        for name, text in sorted(dispatcher._help_lines):
            lines.append(f"  /{name:<12s}  {text}")
        return CommandResult(handled=True, output="\n".join(lines))
    return handler


def _cmd_clear(args: list[str], ctx: CommandContext) -> CommandResult:
    ctx.on_clear()
    return CommandResult(handled=True, output="conversation cleared", clear_log=True)


def _cmd_model(args: list[str], ctx: CommandContext) -> CommandResult:
    if not args:
        current = ctx.session.provider.name
        target = "gemini" if current == "anthropic" else "anthropic"
    else:
        target = args[0].lower()
        if target not in ("anthropic", "gemini"):
            return CommandResult(handled=True, output=f"unknown provider: {target}")
    try:
        ctx.on_switch_model(target)
        return CommandResult(handled=True, output=f"switched to {target}")
    except Exception as exc:  # noqa: BLE001
        return CommandResult(handled=True, output=f"error: {exc}")


def _cmd_tokens(args: list[str], ctx: CommandContext) -> CommandResult:
    s = ctx.session
    return CommandResult(
        handled=True,
        output=f"in={s.total_input_tokens:,} out={s.total_output_tokens:,} messages={len(s.messages)}",
    )


def _cmd_status(args: list[str], ctx: CommandContext) -> CommandResult:
    s = ctx.session
    lines = [
        f"provider: {s.provider.name}:{s.provider.model}",
        f"cwd: {s.cwd}",
        f"messages: {len(s.messages)}",
        f"tokens: in={s.total_input_tokens:,} out={s.total_output_tokens:,}",
        f"tools: {len(s.tools)}",
        f"session_id: {s.session_id}",
    ]
    return CommandResult(handled=True, output="\n".join(lines))


def _cmd_compact(args: list[str], ctx: CommandContext) -> CommandResult:
    ctx.on_compact_now()
    return CommandResult(handled=True, output="compaction scheduled")


def _cmd_rename(args: list[str], ctx: CommandContext) -> CommandResult:
    if not args:
        return CommandResult(handled=True, output="usage: /rename <new title>")
    title = " ".join(args)
    ctx.set_title(title)
    return CommandResult(handled=True, output=f"renamed to: {title}")


def _cmd_theme(args: list[str], ctx: CommandContext) -> CommandResult:
    ctx.on_toggle_theme()
    return CommandResult(handled=True, output="theme toggled")


def _cmd_init(args: list[str], ctx: CommandContext) -> CommandResult:
    ctx.on_init()
    return CommandResult(handled=True, output="creating starter CLAUDE.md …")


def _cmd_memory(args: list[str], ctx: CommandContext) -> CommandResult:
    from .memory import load_memory
    text = load_memory(ctx.session.cwd)
    if not text:
        return CommandResult(handled=True, output="(no CLAUDE.md memory files found)")
    return CommandResult(handled=True, output=text)


def _cmd_todos(args: list[str], ctx: CommandContext) -> CommandResult:
    todos = getattr(ctx.session, "todos", None)
    if not todos:
        return CommandResult(handled=True, output="(no todos)")
    lines = ["# Todos"]
    for t in todos:
        status = t.get("status", "pending")
        mark = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}.get(status, "[?]")
        lines.append(f"  {mark} {t.get('content', '')}")
    return CommandResult(handled=True, output="\n".join(lines))


def _cmd_cwd(args: list[str], ctx: CommandContext) -> CommandResult:
    return CommandResult(handled=True, output=ctx.session.cwd)


def _cmd_version(args: list[str], ctx: CommandContext) -> CommandResult:
    from . import __version__
    return CommandResult(handled=True, output=f"openh {__version__}")


def _cmd_tools(args: list[str], ctx: CommandContext) -> CommandResult:
    lines = ["# Available tools"]
    for tool in ctx.session.tools:
        kind = "read-only" if tool.is_read_only else ("destructive" if tool.is_destructive else "write")
        lines.append(f"  • {tool.name} ({kind}) — {tool.description[:80]}")
    return CommandResult(handled=True, output="\n".join(lines))


def _cmd_providers(args: list[str], ctx: CommandContext) -> CommandResult:
    from .providers import PROVIDER_NAMES
    return CommandResult(
        handled=True,
        output="providers: " + ", ".join(PROVIDER_NAMES) + f"\nactive: {ctx.session.provider.name}",
    )


def _cmd_system(args: list[str], ctx: CommandContext) -> CommandResult:
    from .config import SYSTEM_PROMPT_FILE, load_system_prompt
    import os
    prompt = load_system_prompt()
    source = "built-in default"
    if os.environ.get("OPENH_SYSTEM_PROMPT"):
        source = "OPENH_SYSTEM_PROMPT env var"
    elif SYSTEM_PROMPT_FILE.exists():
        source = str(SYSTEM_PROMPT_FILE)
    return CommandResult(
        handled=True,
        output=f"# System prompt\nsource: {source}\nlength: {len(prompt)} chars\n\n{prompt}",
    )


def _cmd_config(args: list[str], ctx: CommandContext) -> CommandResult:
    import os
    from pathlib import Path
    from .config import (
        ANTHROPIC_DEFAULT_MODEL,
        AUTO_COMPACT_THRESHOLD,
        OPENH_DIR,
        DOTENV_PATH,
        GEMINI_DEFAULT_MODEL,
        MAX_OUTPUT_TOKENS,
        SYSTEM_PROMPT_FILE,
    )
    from .persistence import SESSIONS_DIR

    s = ctx.session
    has_anth = bool(s.config.anthropic_api_key)
    has_gem = bool(s.config.gemini_api_key)
    mcp_path = Path(OPENH_DIR) / "mcp.json"
    hooks_path = Path(OPENH_DIR) / "hooks.json"

    lines = [
        "# Effective configuration",
        "",
        "## Models (change via env vars)",
        f"  Anthropic: {s.config.anthropic_model}   [OPENH_ANTHROPIC_MODEL, default {ANTHROPIC_DEFAULT_MODEL}]",
        f"  Gemini:    {s.config.gemini_model}   [OPENH_GEMINI_MODEL, default {GEMINI_DEFAULT_MODEL}]",
        f"  Active:    {s.provider.name}:{s.provider.model}",
        "",
        "## API keys",
        f"  ANTHROPIC_API_KEY: {'set' if has_anth else 'not set'}",
        f"  GEMINI_API_KEY:    {'set' if has_gem else 'not set'}",
        f"  .env file:         {DOTENV_PATH}  {'(exists)' if Path(DOTENV_PATH).exists() else '(missing)'}",
        "",
        "## Runtime parameters",
        f"  max_output_tokens:    {MAX_OUTPUT_TOKENS}",
        f"  auto_compact_thresh:  {AUTO_COMPACT_THRESHOLD:,} tokens",
        f"  sessions_dir:         {SESSIONS_DIR}",
        f"  system_prompt_file:   {SYSTEM_PROMPT_FILE}  {'(exists)' if SYSTEM_PROMPT_FILE.exists() else '(missing)'}",
        f"  mcp_config:           {mcp_path}  {'(exists)' if mcp_path.exists() else '(missing)'}",
        f"  hooks_config:         {hooks_path}  {'(exists)' if hooks_path.exists() else '(missing)'}",
        "",
        "## Current session",
        f"  session_id: {s.session_id}",
        f"  messages:   {len(s.messages)}",
        f"  tools:      {len(s.tools)}  ({', '.join(t.name for t in s.tools[:13])}{'…' if len(s.tools) > 13 else ''})",
        f"  read_files: {len(s.read_files)}",
        f"  cwd:        {s.cwd}",
    ]
    return CommandResult(handled=True, output="\n".join(lines))
