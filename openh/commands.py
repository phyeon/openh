"""Slash command dispatcher.

Commands intercept user input before it reaches the model. Each command gets
a Context object (session, ui hooks) and returns a CommandResult.
"""
from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from .session import AgentSession


@dataclass
class CommandResult:
    handled: bool
    output: str = ""          # Text to display as a system note (if any)
    user_message: str = ""    # Synthetic user message to send to the model
    clear_log: bool = False   # Whether the UI should clear the log
    refresh_status: bool = False
    quit: bool = False


@dataclass
class CommandContext:
    session: "AgentSession"
    on_clear: Callable[[], None]
    on_switch_model: Callable[[str], None]  # arg: provider name
    on_set_model: Callable[[str], None]     # arg: provider/model or bare model
    on_toggle_theme: Callable[[], None]
    on_compact_now: Callable[[], None]
    on_init: Callable[[], None]
    set_title: Callable[[str], None]
    on_set_output_style: Callable[[str], None]


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
        try:
            parts = shlex.split(text[1:])
        except ValueError:
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
        self.register("model", _cmd_model, "Show or switch the current model")
        self.register("switch", _cmd_model, "Alias for /model")
        self.register("tokens", _cmd_tokens, "Show current token usage")
        self.register("status", _cmd_status, "Show session status")
        self.register("compact", _cmd_compact, "Request a manual conversation compact")
        self.register("max-turns", _cmd_max_turns, "Show or set the current session max turns")
        self.register("max_turns", _cmd_max_turns, "Alias for /max-turns")
        self.register("rename", _cmd_rename, "Rename the current conversation: /rename new title")
        self.register("theme", _cmd_theme, "Toggle light/dark theme")
        self.register("init", _cmd_init, "Generate a starter AGENTS.md in the current directory")
        self.register("memory", _cmd_memory, "Show loaded AGENTS.md / CLAUDE.md memory")
        self.register("todos", _cmd_todos, "Show the current todo list")
        self.register("cwd", _cmd_cwd, "Show the current working directory")
        self.register("version", _cmd_version, "Show openh version")
        self.register("tools", _cmd_tools, "List available tools")
        self.register("providers", _cmd_providers, "List available model providers")
        self.register("system", _cmd_system, "Show the active system prompt")
        self.register("config", _cmd_config, "Show effective configuration (env + files)")
        self.register("output-style", _cmd_output_style, "Show or set output style")
        self.register("output_style", _cmd_output_style, "Alias for /output-style")


def _cmd_help(dispatcher: "CommandDispatcher"):
    def handler(args: list[str], ctx: CommandContext) -> CommandResult:
        if args:
            target = args[0].lower()
            for name, text in dispatcher._help_lines:
                if name == target:
                    return CommandResult(handled=True, output=f"/{name}\n\n{text}")
            return CommandResult(handled=True, output=f"unknown command: /{target}")
        lines = ["# Slash commands", ""]
        for name, text in sorted(dispatcher._help_lines):
            lines.append(f"  /{name:<12s}  {text}")
        lines.extend(["", "Use /help <command> for more detail."])
        return CommandResult(handled=True, output="\n".join(lines))
    return handler


def _cmd_clear(args: list[str], ctx: CommandContext) -> CommandResult:
    ctx.on_clear()
    return CommandResult(handled=True, clear_log=True)


def _cmd_model(args: list[str], ctx: CommandContext) -> CommandResult:
    if not args:
        return CommandResult(
            handled=True,
            output=f"current model: {ctx.session.provider.name}/{ctx.session.provider.model}",
        )
    target = args[0].strip()
    try:
        ctx.on_set_model(target)
        if "/" in target:
            provider, model = target.split("/", 1)
            shown = model if provider == "anthropic" else f"{provider}/{model}"
        else:
            shown = f"{ctx.session.provider.name}/{target}"
        return CommandResult(handled=True, output=f"switched to {shown}")
    except Exception as exc:  # noqa: BLE001
        return CommandResult(handled=True, output=f"error: {exc}")


def _cmd_tokens(args: list[str], ctx: CommandContext) -> CommandResult:
    s = ctx.session
    total_tokens = (
        s.total_input_tokens
        + s.total_output_tokens
        + s.total_cache_creation_input_tokens
        + s.total_cache_read_input_tokens
    )
    subagent_tokens = (
        s.subagent_total_input_tokens
        + s.subagent_total_output_tokens
        + s.subagent_total_cache_creation_input_tokens
        + s.subagent_total_cache_read_input_tokens
    )
    return CommandResult(
        handled=True,
        output=(
            f"total={total_tokens:,} "
            f"in={s.total_input_tokens:,} "
            f"out={s.total_output_tokens:,} "
            f"cache={s.total_cache_creation_input_tokens:,}/{s.total_cache_read_input_tokens:,} "
            f"subagents={subagent_tokens:,} "
            f"cost=${s.total_estimated_cost_usd:.4f} "
            f"messages={len(s.messages)}"
        ),
    )


def _cmd_status(args: list[str], ctx: CommandContext) -> CommandResult:
    s = ctx.session
    total_tokens = (
        s.total_input_tokens
        + s.total_output_tokens
        + s.total_cache_creation_input_tokens
        + s.total_cache_read_input_tokens
    )
    subagent_tokens = (
        s.subagent_total_input_tokens
        + s.subagent_total_output_tokens
        + s.subagent_total_cache_creation_input_tokens
        + s.subagent_total_cache_read_input_tokens
    )
    lines = [
        f"provider: {s.provider.name}:{s.provider.model}",
        f"permission_mode: {getattr(s, 'permission_mode', 'default')}",
        f"cwd: {s.cwd}",
        f"messages: {len(s.messages)}",
        (
            "tokens: "
            f"total={total_tokens:,} "
            f"in={s.total_input_tokens:,} "
            f"out={s.total_output_tokens:,} "
            f"cache_create={s.total_cache_creation_input_tokens:,} "
            f"cache_read={s.total_cache_read_input_tokens:,}"
        ),
        f"subagent_tokens: {subagent_tokens:,}",
        f"cost: ${s.total_estimated_cost_usd:.4f}",
        f"tools: {len(s.tools)}",
        f"max_turns: {getattr(s, 'max_turns', 10)}",
        f"session_id: {s.session_id}",
        f"title: {s.title or '(untitled)'}",
        f"output_style: {getattr(s, 'output_style', 'default')}",
    ]
    return CommandResult(handled=True, output="\n".join(lines))


def _cmd_compact(args: list[str], ctx: CommandContext) -> CommandResult:
    instruction = (
        "Please create a detailed summary of our conversation so far, preserving "
        "key technical details, decisions, file paths, and current task status."
    )
    if args:
        instruction = " ".join(args).strip() or instruction
    return CommandResult(
        handled=True,
        user_message=(
            f"[Compact requested ({len(ctx.session.messages)} messages). "
            f"Instruction: {instruction}]"
        ),
    )


def _cmd_max_turns(args: list[str], ctx: CommandContext) -> CommandResult:
    current = max(1, int(getattr(ctx.session, "max_turns", 10) or 10))
    if not args:
        return CommandResult(handled=True, output=f"current max_turns: {current}")
    raw = (args[0] or "").strip().lower()
    if raw in {"default", "reset"}:
        ctx.session.max_turns = 10
        return CommandResult(handled=True, output="max_turns reset to 10")
    try:
        value = int(raw)
    except Exception:
        return CommandResult(handled=True, output="usage: /max-turns <number|default>")
    if value < 1:
        return CommandResult(handled=True, output="max_turns must be >= 1")
    ctx.session.max_turns = value
    return CommandResult(handled=True, output=f"max_turns set to {value}")


def _cmd_rename(args: list[str], ctx: CommandContext) -> CommandResult:
    if not args:
        title = (ctx.session.title or "").strip()
        if not title:
            for msg in ctx.session.messages:
                if msg.role != "user":
                    continue
                for block in msg.content:
                    if getattr(block, "type", "") != "text":
                        continue
                    text = getattr(block, "text", "").strip()
                    if text:
                        title = text.splitlines()[0][:60].strip()
                        break
                if title:
                    break
        if not title:
            return CommandResult(handled=True, output="usage: /rename <new title>")
        slug = _slugify_title(title)
        if not slug:
            return CommandResult(handled=True, output="usage: /rename <new title>")
        ctx.set_title(slug)
        return CommandResult(handled=True, output=f"renamed to: {slug}")
    title = " ".join(args)
    ctx.set_title(title)
    return CommandResult(handled=True, output=f"renamed to: {title}")


def _cmd_theme(args: list[str], ctx: CommandContext) -> CommandResult:
    ctx.on_toggle_theme()
    return CommandResult(handled=True, output="theme toggled")


def _cmd_init(args: list[str], ctx: CommandContext) -> CommandResult:
    ctx.on_init()
    return CommandResult(handled=True, output="creating starter AGENTS.md …")


def _cmd_memory(args: list[str], ctx: CommandContext) -> CommandResult:
    from .memory import load_memory
    text = load_memory(ctx.session.cwd)
    if not text:
        return CommandResult(handled=True, output="(no AGENTS.md / CLAUDE.md memory files found)")
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
        OPENAI_DEFAULT_MODEL,
        ANTHROPIC_DEFAULT_MODEL,
        AUTO_COMPACT_THRESHOLD,
        OPENH_DIR,
        dotenv_paths,
        GEMINI_DEFAULT_MODEL,
        MAX_OUTPUT_TOKENS,
        SYSTEM_PROMPT_FILE,
    )
    from .output_styles import available_style_names
    from .persistence import sessions_dir

    s = ctx.session
    has_openai = bool(s.config.openai_api_key)
    has_anth = bool(s.config.anthropic_api_key)
    has_gem = bool(s.config.gemini_api_key)
    mcp_path = Path(OPENH_DIR) / "mcp.json"
    hooks_path = Path(OPENH_DIR) / "hooks.json"

    lines = [
        "# Effective configuration",
        "",
        "## Models (change via env vars)",
        f"  OpenAI:   {s.config.openai_model}   [OPENH_OPENAI_MODEL, default {OPENAI_DEFAULT_MODEL}]",
        f"  Anthropic: {s.config.anthropic_model}   [OPENH_ANTHROPIC_MODEL, default {ANTHROPIC_DEFAULT_MODEL}]",
        f"  Gemini:    {s.config.gemini_model}   [OPENH_GEMINI_MODEL, default {GEMINI_DEFAULT_MODEL}]",
        f"  Active:    {s.provider.name}:{s.provider.model}",
        "",
        "## API keys",
        f"  OPENAI_API_KEY:    {'set' if has_openai else 'not set'}",
        f"  ANTHROPIC_API_KEY: {'set' if has_anth else 'not set'}",
        f"  GEMINI_API_KEY:    {'set' if has_gem else 'not set'}",
        "  env files:         "
        + ", ".join(
            f"{path}  {'(exists)' if Path(path).exists() else '(missing)'}"
            for path in dotenv_paths()
        ),
        "",
        "## Runtime parameters",
        f"  max_output_tokens:    {MAX_OUTPUT_TOKENS}",
        f"  auto_compact_thresh:  {AUTO_COMPACT_THRESHOLD:,} tokens",
        f"  sessions_dir:         {sessions_dir()}",
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
        f"  output_style: {getattr(s, 'output_style', 'default')}",
        f"  output_style_options: {', '.join(available_style_names(s.cwd))}",
    ]
    return CommandResult(handled=True, output="\n".join(lines))


def _cmd_output_style(args: list[str], ctx: CommandContext) -> CommandResult:
    from .output_styles import all_styles, find_style

    current = getattr(ctx.session, "output_style", "default") or "default"
    styles = all_styles(ctx.session.cwd)
    if not args:
        lines = [f"current output style: {current}", "", "available styles:"]
        for style in styles:
            desc = f" — {style.description}" if style.description else ""
            lines.append(f"  {style.name}{desc}")
        return CommandResult(handled=True, output="\n".join(lines))

    target = args[0].strip().lower()
    style = find_style(target, ctx.session.cwd)
    if style is None:
        return CommandResult(
            handled=True,
            output=(
                f"unknown output style: {target}\n"
                f"available: {', '.join(style.name for style in styles)}"
            ),
        )
    ctx.on_set_output_style(style.name)
    desc = f" — {style.description}" if style.description else ""
    return CommandResult(handled=True, output=f"output style set to {style.name}{desc}")


def _slugify_title(text: str) -> str:
    out: list[str] = []
    prev_dash = False
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
            continue
        if ch in {" ", "_", "-", "/", ":"} and not prev_dash:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-")[:60]
