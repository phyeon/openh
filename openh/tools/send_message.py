"""SendMessage tool — communicate with a running sub-agent."""
from __future__ import annotations

import asyncio
from typing import Any

from .agent_tool import (
    coordinator_identity,
    find_subagent_entry,
    get_coordination_root,
    get_subagent_registry,
    pending_subagent_message_count,
    poll_background_agent,
    queue_coordinator_message,
    queue_subagent_message,
    run_subagent_prompt,
)
from .base import PermissionDecision, PermissionLevel, Tool, ToolContext


class SendMessageTool(Tool):
    name = "SendMessage"
    permission_level = PermissionLevel.NONE
    description = (
        "Send a message to another agent by name, or broadcast to all active agents with to='*'. "
        "Messages are queued for running agents and delivered in order. "
        "Use message='__status__' to inspect a worker's current state."
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
            "summary": {
                "type": "string",
                "description": "Optional 5-10 word preview for the UI.",
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
        to = str(input.get("to", "")).strip()
        message = str(input.get("message", "")).strip()
        summary = str(input.get("summary", "")).strip()
        coordination_root = get_coordination_root(ctx.session)
        sender_id = ctx.session.session_id or coordinator_identity(ctx.session)
        if not to:
            return "Error: agent target is required."
        if not message:
            return "Error: message cannot be empty."

        if to == "*":
            registry = get_subagent_registry(coordination_root)
            if not registry:
                return "Broadcast queued (no active recipient inboxes yet)."
            recipients = [
                entry
                for entry in registry.values()
                if str(entry.get("id") or "") and str(entry.get("id") or "") != sender_id
            ]
            for agent_entry in recipients:
                queue_subagent_message(
                    coordination_root,
                    str(agent_entry.get("id") or ""),
                    sender=sender_id,
                    content=message,
                    summary=summary,
                )
                self._ensure_delivery(agent_entry, ctx)
            preview = summary or message[:60]
            return f"Broadcast to {len(recipients)} agent(s): {preview}"

        if to in {"coordinator", "manager", coordinator_identity(ctx.session)}:
            queue_coordinator_message(
                coordination_root,
                sender=sender_id,
                content=message,
                summary=summary,
            )
            preview = summary or message[:60]
            return f"Message sent to '{coordinator_identity(ctx.session)}': {preview}"

        agent_entry = find_subagent_entry(coordination_root, to)
        if agent_entry is None:
            return f"Error: agent '{to}' not found."

        if message == "__status__":
            status = agent_entry.get("status", "unknown")
            error = agent_entry.get("error", "")
            last_output = agent_entry.get("last_output", "")
            queued = pending_subagent_message_count(
                coordination_root,
                str(agent_entry.get("id") or ""),
            )
            polled = poll_background_agent(coordination_root, str(agent_entry.get("id") or ""))
            if polled is not None:
                agent_entry["last_output"] = polled
                if polled.startswith("[Agent error"):
                    agent_entry["status"] = "error"
                    agent_entry["error"] = polled
                else:
                    agent_entry["status"] = "idle"
                return polled
            if status == "running":
                return f"Agent {agent_entry.get('id')} is still running. queued_messages={queued}"
            if error:
                return f"Agent {agent_entry.get('id')} error: {error}"
            return last_output or f"Agent {agent_entry.get('id')} is idle. queued_messages={queued}"

        queue_subagent_message(
            coordination_root,
            str(agent_entry.get("id") or ""),
            sender=sender_id,
            content=message,
            summary=summary,
        )
        preview = summary or message[:60]
        if agent_entry.get("status") == "running":
            queued = pending_subagent_message_count(
                coordination_root,
                str(agent_entry.get("id") or ""),
            )
            return f"Message queued for '{agent_entry.get('id')}': {preview} (queued={queued})"

        self._ensure_delivery(agent_entry, ctx)
        return f"Message sent to '{agent_entry.get('id')}': {preview}"

    @staticmethod
    def _ensure_delivery(agent_entry: dict[str, Any], ctx: ToolContext) -> None:
        task = agent_entry.get("task")
        if task is not None and not task.done():
            return

        async def runner() -> None:
            try:
                output = await run_subagent_prompt(
                    agent_entry,
                    "",
                    get_coordination_root(ctx.session),
                )
                agent_entry["last_output"] = output
            finally:
                agent_entry["task"] = None

        agent_entry["task"] = asyncio.create_task(runner())
