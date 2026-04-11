"""Plan mode tools — EnterPlanMode / ExitPlanMode."""
from __future__ import annotations

from typing import Any, ClassVar

from .base import PermissionDecision, Tool, ToolContext


class EnterPlanModeTool(Tool):
    name: ClassVar[str] = "EnterPlanMode"
    description: ClassVar[str] = (
        "Use this tool proactively when you're about to start a non-trivial implementation task. "
        "Getting user sign-off on your approach before writing code prevents wasted effort. "
        "In plan mode, explore the codebase and design an implementation approach for user approval. "
        "Use for: new features, multiple valid approaches, code modifications, multi-file changes."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
    }
    is_read_only: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        setattr(ctx.session, "plan_mode", True)
        return (
            "Entered plan mode. Explore freely with read-only tools, then present your plan "
            "and call ExitPlanMode when ready for user approval."
        )


class ExitPlanModeTool(Tool):
    name: ClassVar[str] = "ExitPlanMode"
    description: ClassVar[str] = (
        "Exit plan mode and present your finalized plan to the user for approval. "
        "The plan is saved to ~/.claude/plans/<name>.md for future reference."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "plan": {
                "type": "string",
                "description": "The finalized implementation plan (markdown).",
            },
            "name": {
                "type": "string",
                "description": "Optional plan name (becomes the filename stem).",
            },
        },
        "required": ["plan"],
    }
    is_read_only: ClassVar[bool] = False
    is_destructive: ClassVar[bool] = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="ask")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        plan = (input.get("plan") or "").strip()
        setattr(ctx.session, "plan_mode", False)
        if not plan:
            return "error: plan is required"

        from ..cc_compat import PLANS_DIR
        import random
        import re
        name = (input.get("name") or "").strip()
        if not name:
            adjs = ["jazzy", "swift", "bold", "calm", "eager", "cozy", "glowing"]
            nouns = ["plan", "sketch", "blueprint", "outline", "draft"]
            name = "-".join([
                random.choice(adjs),
                random.choice(adjs),
                random.choice(nouns),
            ])
        safe = re.sub(r"[^a-z0-9가-힣_\- ]+", "", name.lower())
        safe = re.sub(r"\s+", "-", safe) or "plan"
        PLANS_DIR.mkdir(parents=True, exist_ok=True)
        path = PLANS_DIR / f"{safe}.md"
        try:
            path.write_text(plan, encoding="utf-8")
        except OSError as exc:
            return f"error: plan write failed: {exc}"

        return f"Plan saved to {path}.\n\n# Approved plan\n\n{plan}"
