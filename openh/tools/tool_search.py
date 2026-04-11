"""ToolSearch — search available tools by keyword."""
from __future__ import annotations

from typing import Any

from .base import PermissionDecision, Tool, ToolContext


class ToolSearchTool(Tool):
    name = "ToolSearch"
    description = (
        "Search for available tools by keyword. Returns matching tool names "
        "and descriptions. Useful when the agent needs to discover which "
        "tools are available for a specific task."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search keyword to match against tool names and descriptions.",
            },
        },
        "required": ["query"],
    }
    is_read_only = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        query = input.get("query", "").lower()
        if not query:
            return "Error: query is required."

        matches = []
        for tool in ctx.session.tools:
            name = getattr(tool, "name", "")
            desc = getattr(tool, "description", "")
            if query in name.lower() or query in desc.lower():
                matches.append(f"  {name} — {desc[:100]}")

        if not matches:
            return f"No tools matching '{query}'."
        return f"Found {len(matches)} tool(s):\n" + "\n".join(matches)
