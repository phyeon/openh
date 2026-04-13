"""Sleep tool — wait without holding a shell process."""
from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext

MAX_SLEEP_MS = 300_000


class SleepTool(Tool):
    name: ClassVar[str] = "Sleep"
    permission_level = PermissionLevel.NONE
    description: ClassVar[str] = (
        "Wait for a specified duration in milliseconds. "
        "Use instead of Bash(sleep ...) — it doesn't hold a shell process "
        "and can run concurrently with other tools. "
        "The user can interrupt the sleep at any time."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "ms": {
                "type": "number",
                "description": "Duration to sleep in milliseconds (max 300000 = 5 minutes)",
            }
        },
        "required": ["ms"],
    }
    is_read_only: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        try:
            duration_ms = int(input.get("ms") or 0)
        except Exception:
            return "error: ms must be a number"
        if duration_ms < 0:
            duration_ms = 0
        duration_ms = min(duration_ms, MAX_SLEEP_MS)
        await asyncio.sleep(duration_ms / 1000.0)
        return f"Slept for {duration_ms}ms."
