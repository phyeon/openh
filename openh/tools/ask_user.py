"""AskUserQuestion tool — prompt the user with a structured question."""
from __future__ import annotations

from typing import Any

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext


class AskUserQuestionTool(Tool):
    name = "AskUserQuestion"
    permission_level = PermissionLevel.NONE
    description = (
        "Ask the user a question with optional choices. Use this to gather "
        "preferences, clarify requirements, or get decisions on implementation "
        "choices."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question to ask the user.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of choices for the user to pick from.",
            },
        },
        "required": ["question"],
    }
    is_read_only = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        question = input.get("question", "")
        options = input.get("options", [])
        parts = [f"Question: {question}"]
        if options:
            parts.append("Options:")
            for i, opt in enumerate(options, 1):
                parts.append(f"  {i}. {opt}")
        # The question is rendered in the UI; the agent receives the text
        # back so it can reason about the user's answer.
        return "\n".join(parts)
