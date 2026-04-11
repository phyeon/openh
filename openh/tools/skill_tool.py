"""Skill tool — invoke a named skill from ~/.claude/skills/."""
from __future__ import annotations

from typing import Any, ClassVar

from .. import skills
from .base import PermissionDecision, Tool, ToolContext


class SkillTool(Tool):
    name: ClassVar[str] = "Skill"
    description: ClassVar[str] = (
        "Execute a named skill. Skills live under ~/.claude/skills/ and encode "
        "domain-specific workflows. The tool returns the skill's full instructions "
        "which you should then follow. Call `list_skills=true` with no name to "
        "discover available skills."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "Skill name (matches the `name` field in SKILL.md frontmatter).",
            },
            "args": {
                "type": "string",
                "description": "Optional arguments to pass to the skill.",
            },
            "list_skills": {
                "type": "boolean",
                "description": "If true, list available skills instead of executing one.",
            },
        },
    }
    is_read_only: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        if input.get("list_skills"):
            all_skills = skills.list_skills()
            if not all_skills:
                return "(no skills installed)"
            lines = [f"{len(all_skills)} skill(s) available:"]
            for s in all_skills:
                lines.append(f"  {s.name} — {s.description}")
            return "\n".join(lines)

        name = (input.get("skill") or "").strip()
        if not name:
            return "error: skill name is required (or pass list_skills=true)"
        skill = skills.get_skill(name)
        if skill is None:
            return f"error: unknown skill '{name}'"
        args = (input.get("args") or "").strip()
        body = skill.body
        suffix = f"\n\n[invoked with args: {args}]" if args else ""
        return f"# Skill: {skill.name}\n\n{body}{suffix}"
