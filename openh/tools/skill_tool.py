"""Skill tool — invoke a named skill from ~/.claude/skills/."""
from __future__ import annotations

from typing import Any, ClassVar

from .. import skills
from .base import PermissionDecision, Tool, ToolContext


class SkillTool(Tool):
    name: ClassVar[str] = "Skill"
    description: ClassVar[str] = (
        "Execute a skill by name. Use skill='list' to discover available skills. "
        "The expanded skill instructions are returned inline for you to follow."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "skill": {
                "type": "string",
                "description": "Skill name, or 'list' to enumerate skills.",
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
        skill_name = (input.get("skill") or "").strip()
        if input.get("list_skills") or skill_name.lower() == "list":
            all_skills = skills.list_skills()
            if not all_skills:
                return "No skills found."
            lines = [f"Available skills ({len(all_skills)}):"]
            for s in all_skills:
                description = s.description or "(no description)"
                lines.append(f"  {s.name} — {description}")
            return "\n".join(lines)

        name = skill_name.removesuffix(".md")
        if not name:
            return "error: skill name is required (or use skill='list')"
        skill = skills.get_skill(name)
        if skill is None:
            return f"error: unknown skill '{name}'. Use skill='list' to see available skills."
        args = (input.get("args") or "").strip()
        body = skill.body
        if args:
            body = body.replace("$ARGUMENTS", args)
        else:
            body = body.replace("$ARGUMENTS", "")
        body = body.strip()
        if not body:
            return f"error: skill '{skill.name}' expanded to empty content"
        return body
