"""TodoWrite tool — maintain a structured todo list for the current session."""
from __future__ import annotations

from typing import Any, ClassVar

from .base import PermissionDecision, Tool, ToolContext


class TodoWriteTool(Tool):
    name: ClassVar[str] = "TodoWrite"
    description: ClassVar[str] = (
        "Create and manage a structured task list for the current session. "
        "Each todo has: content (imperative), activeForm (present continuous), "
        "and status (pending / in_progress / completed). Exactly one task should "
        "be in_progress at any time. Pass the full replacement list on every call."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Full list of todo items (replaces the previous list).",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Imperative form (e.g. 'Run tests').",
                        },
                        "activeForm": {
                            "type": "string",
                            "description": "Present continuous (e.g. 'Running tests').",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["content", "activeForm", "status"],
                },
            },
        },
        "required": ["todos"],
    }
    is_read_only: ClassVar[bool] = False
    is_destructive: ClassVar[bool] = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        todos = input.get("todos") or []
        if not isinstance(todos, list):
            return "error: todos must be a list"

        # Store on the session so the UI can read it
        if not hasattr(ctx.session, "todos"):
            setattr(ctx.session, "todos", [])
        ctx.session.todos = list(todos)  # type: ignore[attr-defined]

        # Validate that at most one is in_progress
        in_progress = [t for t in todos if t.get("status") == "in_progress"]
        warn = ""
        if len(in_progress) > 1:
            warn = f" (warning: {len(in_progress)} items marked in_progress; should be 1)"

        lines = [f"Todo list updated ({len(todos)} items){warn}"]
        for t in todos:
            status = t.get("status", "pending")
            mark = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}.get(status, "[ ]")
            lines.append(f"  {mark} {t.get('content', '')}")
        return "\n".join(lines)
