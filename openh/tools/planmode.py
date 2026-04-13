"""Plan mode tools — EnterPlanMode / ExitPlanMode."""
from __future__ import annotations

from typing import Any, ClassVar

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext


class EnterPlanModeTool(Tool):
    name: ClassVar[str] = "EnterPlanMode"
    permission_level = PermissionLevel.NONE
    description: ClassVar[str] = (
        "Enter plan mode. In plan mode, the assistant can only read files and "
        "think, but cannot execute commands or write files. Use this to step back "
        "and plan a complex change before implementing it."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Why you want to enter plan mode",
            }
        },
    }
    is_read_only: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        setattr(ctx.session, "plan_mode", True)
        reason = str(input.get("reason") or "").strip()
        if reason:
            return f"Entered plan mode: {reason}"
        return "Entered plan mode. Only read-only operations are allowed."


class ExitPlanModeTool(Tool):
    name: ClassVar[str] = "ExitPlanMode"
    permission_level = PermissionLevel.NONE
    description: ClassVar[str] = (
        "Exit plan mode and return to normal execution mode where all tools "
        "are available. Optionally provide a summary of the plan."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Summary of the plan you developed",
            },
        },
    }
    is_read_only: ClassVar[bool] = False
    is_destructive: ClassVar[bool] = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        setattr(ctx.session, "plan_mode", False)
        summary = str(input.get("summary") or "").strip()
        if summary:
            return f"Exited plan mode. Plan summary: {summary}"
        return "Exited plan mode. All tools are now available."
