"""Agent tool — spawn a sub-agent with its own message history."""
from __future__ import annotations

import asyncio
import tempfile
import uuid
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

from .. import prompts as prompts_mod
from ..config import load_system_prompt
from ..coordinator import INTERNAL_COORDINATOR_TOOLS
from ..providers import get_provider
from ..session import AgentSession
from ..system_prompt import build_runtime_system_prompt
from .base import PermissionDecision, PermissionLevel, Tool, ToolContext

_COORDINATOR_ONLY_TOOLS = set(INTERNAL_COORDINATOR_TOOLS)
_SEARCH_ONLY_TOOLS = {"LS", "Read", "Glob", "Grep", "ToolSearch", "WebFetch", "WebSearch", "Skill"}
_MODE_PROMPTS = {
    "build": "You are the build agent. You have full tool access. Focus on implementing the requested changes completely and correctly.",
    "plan": "You are the plan agent. You can read files and analyze code but cannot write files or execute commands. Focus on understanding the codebase and describing what changes should be made.",
    "explore": "You are the explore agent. You can search and read files. Focus on quickly finding relevant code and answering questions about the codebase.",
}
_MODE_DEFAULT_TURNS = {
    "build": 10,
    "plan": 20,
    "explore": 15,
}


def get_coordination_root(session: AgentSession) -> AgentSession:
    root = getattr(session, "_coordination_root", None)
    if isinstance(root, AgentSession):
        return root
    return session


def coordinator_identity(session: AgentSession) -> str:
    root = get_coordination_root(session)
    return root.session_id or "coordinator"


def get_subagent_registry(session: AgentSession) -> dict[str, dict[str, Any]]:
    root = get_coordination_root(session)
    registry = getattr(root, "_subagent_registry", None)
    if registry is None:
        registry = {}
        setattr(root, "_subagent_registry", registry)
    return registry


def get_subagent_inbox(session: AgentSession) -> dict[str, list[dict[str, Any]]]:
    root = get_coordination_root(session)
    inbox = getattr(root, "_subagent_inbox", None)
    if inbox is None:
        inbox = {}
        setattr(root, "_subagent_inbox", inbox)
    return inbox


def get_coordinator_inbox(session: AgentSession) -> list[dict[str, Any]]:
    root = get_coordination_root(session)
    inbox = getattr(root, "_coordinator_inbox", None)
    if inbox is None:
        inbox = []
        setattr(root, "_coordinator_inbox", inbox)
    return inbox


def queue_subagent_message(
    session: AgentSession,
    recipient_id: str,
    *,
    sender: str,
    content: str,
    summary: str = "",
) -> dict[str, Any]:
    message = {
        "from": sender,
        "to": recipient_id,
        "content": content,
        "summary": summary,
    }
    inbox = get_subagent_inbox(session)
    inbox.setdefault(recipient_id, []).append(message)
    return message


def drain_subagent_messages(session: AgentSession, recipient_id: str) -> list[dict[str, Any]]:
    inbox = get_subagent_inbox(session)
    return list(inbox.pop(recipient_id, []))


def pending_subagent_message_count(session: AgentSession, recipient_id: str) -> int:
    inbox = get_subagent_inbox(session)
    return len(inbox.get(recipient_id, []))


def queue_coordinator_message(
    session: AgentSession,
    *,
    sender: str,
    content: str,
    summary: str = "",
) -> dict[str, Any]:
    message = {
        "from": sender,
        "to": coordinator_identity(session),
        "content": content,
        "summary": summary,
    }
    get_coordinator_inbox(session).append(message)
    return message


def drain_coordinator_messages(session: AgentSession) -> list[dict[str, Any]]:
    inbox = get_coordinator_inbox(session)
    items = list(inbox)
    inbox.clear()
    return items


def find_subagent_entry(session: AgentSession, target: str) -> dict[str, Any] | None:
    registry = get_subagent_registry(session)
    if target in registry:
        return registry[target]

    lowered = target.lower()
    for entry in registry.values():
        agent_id = str(entry.get("id", ""))
        name = str(entry.get("name", ""))
        if agent_id.startswith(target) or name.lower().startswith(lowered):
            return entry
    return None


def extract_subagent_text(entry: dict[str, Any]) -> str:
    text = str(entry.get("last_output", "")).strip()
    if text:
        return text

    agent = entry.get("agent")
    if agent is None:
        return ""
    messages = getattr(agent.session, "messages", [])
    for msg in reversed(messages):
        if getattr(msg, "role", "") != "assistant":
            continue
        parts: list[str] = []
        for block in msg.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        text = "".join(parts).strip()
        if text:
            entry["last_output"] = text
            return text
    return ""


def _format_queued_messages(messages: list[dict[str, Any]]) -> str:
    if not messages:
        return ""
    lines = [
        "You have received queued coordinator messages while working. "
        "Incorporate anything relevant before continuing.",
    ]
    for message in messages:
        sender = str(message.get("from") or "coordinator")
        summary = str(message.get("summary") or "").strip()
        suffix = f" ({summary})" if summary else ""
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"- From {sender}{suffix}: {content}")
    return "\n".join(lines).strip()


async def run_subagent_prompt(
    entry: dict[str, Any],
    prompt: str,
    parent: AgentSession,
) -> str:
    agent = entry["agent"]
    entry["status"] = "running"
    entry["error"] = ""
    next_prompt = (prompt or "").strip()
    output = str(entry.get("last_output", "")).strip()

    while True:
        queued_messages = drain_subagent_messages(
            get_coordination_root(parent),
            str(entry.get("id") or ""),
        )
        pieces: list[str] = []
        if next_prompt:
            pieces.append(next_prompt)
        queued_text = _format_queued_messages(queued_messages)
        if queued_text:
            pieces.append(queued_text)
        if not pieces:
            break

        try:
            await agent.run_turn("\n\n".join(pieces))
        except Exception as exc:  # noqa: BLE001
            entry["status"] = "error"
            entry["error"] = str(exc)
            return f"sub-agent failed: {exc}"

        parent.read_files.update(agent.session.read_files)
        output = extract_subagent_text(entry) or "(sub-agent finished without text output)"
        entry["last_output"] = output
        next_prompt = ""

    entry["status"] = "idle"
    return output or "(sub-agent finished without text output)"


async def _find_git_root(start: str) -> Path | None:
    if not start:
        return None

    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            start,
            "rev-parse",
            "--show-toplevel",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError:
        return None

    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return None

    root = stdout.decode("utf-8", errors="replace").strip()
    if not root:
        return None
    return Path(root)


async def _create_isolated_worktree(parent_cwd: str, agent_id: str) -> tuple[str, Path | None, Path | None]:
    git_root = await _find_git_root(parent_cwd)
    if git_root is None:
        return parent_cwd, None, None

    worktree_dir = Path(tempfile.gettempdir()) / f"openh-agent-{agent_id}"
    if worktree_dir.exists():
        return str(worktree_dir), worktree_dir, git_root

    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(git_root),
            "worktree",
            "add",
            "--detach",
            str(worktree_dir),
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError:
        return parent_cwd, None, None

    await proc.communicate()
    if proc.returncode != 0 or not worktree_dir.exists():
        return parent_cwd, None, git_root

    return str(worktree_dir), worktree_dir, git_root


class AgentTool(Tool):
    name: ClassVar[str] = "Agent"
    permission_level = PermissionLevel.NONE
    description: ClassVar[str] = (
        "Launch a new agent to handle complex, multi-step tasks autonomously. "
        "The agent runs its own agentic loop with access to tools and returns its final result. "
        "Use this to delegate sub-tasks, run parallel workstreams, or handle tasks that require many tool calls. "
        "Supports optional tool filtering, model overrides, worktree isolation, and background execution."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Short task description (3-5 words).",
            },
            "prompt": {
                "type": "string",
                "description": "The complete task for the agent to perform.",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of tool names to make available. Defaults depend on mode.",
            },
            "mode": {
                "type": "string",
                "enum": ["build", "plan", "explore"],
                "description": "Optional named agent mode. build=full access, plan=read-only analysis, explore=search-first exploration.",
            },
            "system_prompt": {
                "type": "string",
                "description": "Optional system prompt addition for the sub-agent.",
            },
            "max_turns": {
                "type": "integer",
                "description": "Maximum model/tool loop turns for the sub-agent.",
            },
            "model": {
                "type": "string",
                "description": "Optional model override. Accepts bare model id or provider/model.",
            },
            "isolation": {
                "type": "string",
                "enum": ["worktree"],
                "description": "Optional isolation mode. Use worktree to run the agent in a dedicated git worktree.",
            },
            "run_in_background": {
                "type": "boolean",
                "description": "If true, start the agent asynchronously and return an agent id immediately.",
            },
        },
        "required": ["description", "prompt"],
    }
    is_read_only: ClassVar[bool] = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        prompt = (input.get("prompt") or "").strip()
        desc = (input.get("description") or "").strip() or "sub-agent task"
        if not prompt:
            return "error: prompt is required"

        from ..agent import Agent
        from ..messages import StreamEvent, TextDelta

        parent = ctx.session
        mode = str(input.get("mode") or "build").strip().lower()
        if mode not in _MODE_PROMPTS:
            mode = "build"

        try:
            provider, sub_config = self._resolve_provider(
                parent,
                str(input.get("model") or "").strip(),
            )
        except Exception as exc:  # noqa: BLE001
            return f"error: failed to configure sub-agent provider: {exc}"
        tool_names = input.get("tools")
        sub_tools = self._select_tools(parent.tools, tool_names, mode)
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        isolation_supplied = "isolation" in input
        isolation = str(input.get("isolation") or "").strip().lower()
        if not isolation and not isolation_supplied and getattr(parent, "managed_executor_isolation", False):
            isolation = "worktree"
        sub_cwd = parent.cwd
        worktree_dir: Path | None = None
        git_root: Path | None = None
        if isolation == "worktree":
            sub_cwd, worktree_dir, git_root = await _create_isolated_worktree(parent.cwd, agent_id)

        sub = AgentSession(
            config=sub_config,
            provider=provider,
            tools=sub_tools,
        )
        sub.session_id = agent_id
        sub.cwd = sub_cwd
        sub.read_files = set(parent.read_files)
        sub.always_allow = set(parent.always_allow)
        sub.always_deny = set(parent.always_deny)
        sub.permission_mode = parent.permission_mode
        sub.permission_handler_kind = parent.permission_handler_kind
        sub.output_style = parent.output_style
        sub.output_style_prompt = parent.output_style_prompt
        sub.append_system_prompt = parent.append_system_prompt
        sub.replace_system_prompt = parent.replace_system_prompt
        sub.is_non_interactive = True
        sub.prompt_override = parent.prompt_override
        sub.prompt_preset = parent.prompt_preset
        sub.profile_id = parent.profile_id
        sub.shell_env = dict(parent.shell_env)
        sub.managed_agent_enabled = False
        sub.managed_executor_model = parent.managed_executor_model
        sub.managed_executor_max_turns = parent.managed_executor_max_turns
        sub.managed_max_concurrent_executors = parent.managed_max_concurrent_executors
        sub.managed_executor_isolation = parent.managed_executor_isolation
        setattr(sub, "bash_read_only", bool(input.get("_bash_read_only")))
        setattr(sub, "_coordination_root", get_coordination_root(parent))
        setattr(sub, "_usage_parent", get_coordination_root(parent))

        collected: list[str] = []

        async def sink(event: StreamEvent) -> None:
            if isinstance(event, TextDelta):
                collected.append(event.text)

        async def perm(tool_name: str, input_dict: dict[str, Any]) -> bool:
            return await ctx.request_permission(f"[sub-agent] {tool_name}", input_dict)

        system_prompt = self._build_subagent_system_prompt(
            parent,
            mode=mode,
            system_override=(input.get("system_prompt") or "").strip(),
            cwd=sub.cwd,
        )
        sub_agent = Agent(
            session=sub,
            system_prompt=system_prompt,
            event_sink=sink,
            permission_cb=perm,
        )
        default_turns = int(
            getattr(parent, "managed_executor_max_turns", 0) or _MODE_DEFAULT_TURNS[mode]
        )
        max_turns = int(input.get("max_turns") or default_turns)
        if max_turns > 0:
            sub.max_turns = max_turns

        registry = get_subagent_registry(parent)
        entry = {
            "id": agent_id,
            "name": desc,
            "mode": mode,
            "agent": sub_agent,
            "status": "idle",
            "last_output": "",
            "error": "",
            "task": None,
            "isolation": isolation or "",
            "worktree_dir": str(worktree_dir) if worktree_dir is not None else "",
            "git_root": str(git_root) if git_root is not None else "",
        }
        registry[agent_id] = entry

        if bool(input.get("run_in_background")):
            async def runner() -> None:
                output = await run_subagent_prompt(entry, prompt, parent)
                entry["last_output"] = output
                finished_state = "failed" if entry.get("status") == "error" else "finished"
                summary = f"{desc} {finished_state}"
                preview = output.strip()
                if len(preview) > 500:
                    preview = preview[:500].rstrip() + "..."
                queue_coordinator_message(
                    parent,
                    sender=agent_id,
                    content=f"Agent '{desc}' {finished_state}.\n\n{preview or '(no output)'}",
                    summary=summary,
                )

            task = asyncio.create_task(runner())
            entry["task"] = task
            return (
                "{"
                f"\"agent_id\": \"{agent_id}\", "
                f"\"status\": \"running\", "
                f"\"message\": \"Agent '{desc}' started in background.\""
                "}"
            )

        output = await run_subagent_prompt(entry, prompt, parent)
        streamed = "".join(collected).strip()
        if streamed and not output.strip():
            output = streamed
        return f"# {desc}\n\n{output}"

    @staticmethod
    def _select_tools(all_tools: list[Tool], allowed: Any, mode: str) -> list[Tool]:
        requested = {str(name) for name in (allowed or []) if str(name).strip()}
        selected: list[Tool] = []

        for tool in all_tools:
            if tool.name in _COORDINATOR_ONLY_TOOLS:
                continue
            if requested and tool.name not in requested:
                continue
            if not requested and mode == "plan" and not tool.is_read_only:
                continue
            if not requested and mode == "explore" and tool.name not in _SEARCH_ONLY_TOOLS:
                continue
            selected.append(tool)
        return selected

    @staticmethod
    def _resolve_provider(parent: AgentSession, model_spec: str) -> tuple[Any, Any]:
        provider_name = getattr(parent.provider, "name", "anthropic")
        model_name = model_spec

        if model_spec and "/" in model_spec:
            maybe_provider, maybe_model = model_spec.split("/", 1)
            if maybe_provider and maybe_model:
                provider_name, model_name = maybe_provider, maybe_model

        managed_executor_model = (getattr(parent, "managed_executor_model", "") or "").strip()
        if not model_name and managed_executor_model:
            model_name = managed_executor_model
            if "/" in model_name:
                maybe_provider, maybe_model = model_name.split("/", 1)
                if maybe_provider and maybe_model:
                    provider_name, model_name = maybe_provider, maybe_model

        if not model_name:
            return parent.provider, parent.config

        config = parent.config
        if provider_name == "openai":
            config = replace(config, openai_model=model_name)
        elif provider_name == "anthropic":
            config = replace(config, anthropic_model=model_name)
        elif provider_name == "gemini":
            config = replace(config, gemini_model=model_name)
        provider = get_provider(provider_name, config)
        return provider, config

    @staticmethod
    def _session_custom_prompt_text(parent: AgentSession) -> str:
        if parent.prompt_override:
            return parent.prompt_override
        preset_name = (parent.prompt_preset or "").strip()
        if preset_name and preset_name.lower() != prompts_mod.BUILTIN_NAME:
            preset = prompts_mod.get_preset(preset_name)
            if preset is not None and preset.text.strip():
                return preset.text
        return ""

    @classmethod
    def _build_subagent_system_prompt(
        cls,
        parent: AgentSession,
        *,
        mode: str,
        system_override: str,
        cwd: str,
    ) -> str:
        return build_runtime_system_prompt(
            load_system_prompt(),
            cwd,
            date.today().isoformat(),
            custom_prompt=cls._session_custom_prompt_text(parent),
            append_system_prompt=system_override,
            is_non_interactive=True,
            output_style=getattr(parent, "output_style", "default"),
            custom_output_style_prompt=getattr(parent, "output_style_prompt", ""),
        )
