"""SendMessage tool — communicate with a running sub-agent."""
from __future__ import annotations

from typing import Any

from .base import PermissionDecision, Tool, ToolContext


class SendMessageTool(Tool):
    name = "SendMessage"
    description = (
        "Send a follow-up message to a previously spawned sub-agent. "
        "The agent resumes with its full context preserved."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "The agent ID or name to send the message to.",
            },
            "message": {
                "type": "string",
                "description": "The message content to send.",
            },
        },
        "required": ["to", "message"],
    }
    is_read_only = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        to = input.get("to", "")
        message = input.get("message", "")

        # Look for the sub-agent in the session's agent registry
        registry = getattr(ctx.session, "_subagent_registry", None)
        if registry is None:
            return f"Error: no sub-agent registry found. Cannot send message to '{to}'."

        agent_entry = registry.get(to)
        if agent_entry is None:
            # Try matching by name prefix
            for key, entry in registry.items():
                if key.startswith(to) or entry.get("name", "").startswith(to):
                    agent_entry = entry
                    break

        if agent_entry is None:
            available = ", ".join(registry.keys()) if registry else "(none)"
            return f"Error: agent '{to}' not found. Available: {available}"

        sub_agent = agent_entry.get("agent")
        if sub_agent is None:
            return f"Error: agent '{to}' has no active session."

        # Inject the message and run another turn
        sub_agent.session.append_user_text(message)

        try:
            result = await sub_agent.run_turn()
        except Exception as e:
            return f"Error running sub-agent turn: {e}"

        # Extract text from the response
        text_parts = []
        if sub_agent.session.messages:
            last = sub_agent.session.messages[-1]
            if last.role == "assistant":
                for block in last.content:
                    if hasattr(block, "text"):
                        text_parts.append(block.text)
        return "\n".join(text_parts) if text_parts else "(no text response)"
