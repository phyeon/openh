"""Coordinator mode helpers mirrored from the public PB query layer."""
from __future__ import annotations

import os

COORDINATOR_ENV_VAR = "CLAUDE_CODE_COORDINATOR_MODE"

INTERNAL_COORDINATOR_TOOLS = (
    "Agent",
    "SendMessage",
    "TaskStop",
)


def is_coordinator_mode() -> bool:
    value = os.environ.get(COORDINATOR_ENV_VAR, "")
    return bool(value and value not in {"0", "false"})


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


def coordinator_user_context(
    available_tools: list[str],
    mcp_servers: list[str] | None = None,
) -> str:
    tool_list = ", ".join(
        tool
        for tool in available_tools
        if tool not in INTERNAL_COORDINATOR_TOOLS
    )
    mcp_servers = list(mcp_servers or [])
    if mcp_servers:
        return f"Available worker tools: {tool_list}\nConnected MCP servers: {', '.join(mcp_servers)}\n"
    return f"Available worker tools: {tool_list}\n"


def match_session_mode(stored_coordinator: bool) -> str | None:
    current = is_coordinator_mode()
    if stored_coordinator == current:
        return None
    if stored_coordinator:
        os.environ[COORDINATOR_ENV_VAR] = "1"
    else:
        os.environ.pop(COORDINATOR_ENV_VAR, None)
    label = "coordinator" if stored_coordinator else "standard"
    return f"Session was created in {label} mode, switching to match."
