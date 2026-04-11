"""Agent / Task tool — spawn a sub-agent with its own message history.

The sub-agent shares the same tools and provider as the parent. It runs the
parent's prompt in an isolated session and returns its final text output.
"""
from __future__ import annotations

from typing import Any, ClassVar

from .base import PermissionDecision, Tool, ToolContext


class AgentTool(Tool):
    name: ClassVar[str] = "Agent"
    description: ClassVar[str] = (
        "Launch a new agent to handle complex, multi-step tasks autonomously. "
        "Each agent runs in its own session with access to the same tools. "
        "Launch multiple agents concurrently whenever possible, to maximize performance. "
        "Always include a short description (3-5 words) summarizing what the agent will do. "
        "The agent's outputs should generally be trusted. "
        "Clearly tell the agent whether you expect it to write code or just to do research."
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
                "description": "Full task prompt for the sub-agent — explain context and what you want.",
            },
        },
        "required": ["description", "prompt"],
    }
    is_read_only: ClassVar[bool] = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="ask")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        prompt = (input.get("prompt") or "").strip()
        desc = (input.get("description") or "").strip() or "sub-agent task"
        if not prompt:
            return "error: prompt is required"

        from ..agent import Agent
        from ..messages import Message, StreamEvent, TextBlock, TextDelta
        from ..session import AgentSession

        parent = ctx.session
        sub = AgentSession(
            config=parent.config,
            provider=parent.provider,
            tools=parent.tools,
        )
        sub.read_files = set(parent.read_files)
        sub.always_allow = set(parent.always_allow)

        collected: list[str] = []

        async def sink(event: StreamEvent) -> None:
            if isinstance(event, TextDelta):
                collected.append(event.text)

        async def perm(tool_name: str, input_dict: dict[str, Any]) -> bool:
            return await ctx.request_permission(f"[sub-agent] {tool_name}", input_dict)

        sub_agent = Agent(
            session=sub,
            system_prompt="You are a focused sub-agent. Use tools as needed to complete the task, then return a concise final answer.",
            event_sink=sink,
            permission_cb=perm,
        )

        try:
            await sub_agent.run_turn(prompt)
        except Exception as exc:  # noqa: BLE001
            return f"sub-agent failed: {exc}"

        # Roll up any files the sub-agent read back to the parent
        parent.read_files.update(sub.read_files)

        output = "".join(collected).strip()
        if not output:
            output = "(sub-agent finished without text output)"
        return f"# {desc}\n\n{output}"
