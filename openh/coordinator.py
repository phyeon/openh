"""Coordinator mode helpers mirrored from the public query layer."""
from __future__ import annotations

import os

PRIMARY_COORDINATOR_ENV_VAR = "CLAUDE_CODE_COORDINATOR_MODE"
LEGACY_COORDINATOR_ENV_VAR = "CLAURST_COORDINATOR_MODE"
COORDINATOR_ENV_VAR = PRIMARY_COORDINATOR_ENV_VAR

INTERNAL_COORDINATOR_TOOLS = (
    "Agent",
    "SendMessage",
    "TaskStop",
)

COORDINATOR_ONLY_TOOLS = INTERNAL_COORDINATOR_TOOLS


def _truthy_env(name: str) -> bool:
    value = os.environ.get(name, "")
    return bool(value and value not in {"0", "false"})


def is_coordinator_mode() -> bool:
    return _truthy_env(PRIMARY_COORDINATOR_ENV_VAR) or _truthy_env(
        LEGACY_COORDINATOR_ENV_VAR
    )


def set_coordinator_mode(enabled: bool) -> None:
    if enabled:
        os.environ[PRIMARY_COORDINATOR_ENV_VAR] = "1"
        os.environ[LEGACY_COORDINATOR_ENV_VAR] = "1"
        return
    os.environ.pop(PRIMARY_COORDINATOR_ENV_VAR, None)
    os.environ.pop(LEGACY_COORDINATOR_ENV_VAR, None)


def coordinator_system_prompt() -> str:
    return """
## Coordinator Mode

You are operating as an orchestrator for parallel worker agents.

### Your Role
- Orchestrate workers using the Agent tool to spawn parallel subagents
- Use SendMessage to continue communication with running workers
- Use TaskStop to cancel workers that are no longer needed
- Synthesize findings across workers before presenting to the user
- Answer directly when the question doesn't need delegation

### Task Workflow
1. **Research Phase**: Spawn workers to gather information in parallel
2. **Synthesis Phase**: Collect and merge worker findings
3. **Implementation Phase**: Delegate implementation tasks to specialized workers
4. **Verification Phase**: Spawn verification workers to validate results

### Worker Guidelines
- Worker prompts must be fully self-contained (workers cannot see your conversation)
- Always synthesize findings before spawning follow-up workers
- Workers have access to all standard tools + MCP + skills
- Use TaskCreate/TaskUpdate to track parallel work

### Internal Tools (do not delegate to workers)
- Agent, SendMessage, TaskStop (coordination only)
""".strip()


def filter_worker_tool_names(available_tools: list[str]) -> list[str]:
    seen: set[str] = set()
    filtered: list[str] = []
    for tool in available_tools:
        name = str(tool or "").strip()
        if not name or name in INTERNAL_COORDINATOR_TOOLS or name in seen:
            continue
        seen.add(name)
        filtered.append(name)
    return filtered


def coordinator_user_context(
    available_tools: list[str],
    mcp_servers: list[str] | None = None,
) -> str:
    tool_list = ", ".join(filter_worker_tool_names(available_tools))
    mcp_servers = sorted({str(name).strip() for name in (mcp_servers or []) if str(name).strip()})
    if mcp_servers:
        return (
            f"Available worker tools: {tool_list}\n"
            f"Connected MCP servers: {', '.join(mcp_servers)}\n"
        )
    return f"Available worker tools: {tool_list}\n"


def match_session_mode(stored_coordinator: bool) -> str | None:
    current = is_coordinator_mode()
    if stored_coordinator == current:
        return None
    set_coordinator_mode(stored_coordinator)
    if stored_coordinator:
        return "Entered coordinator mode to match resumed session."
    return "Exited coordinator mode to match resumed session."
