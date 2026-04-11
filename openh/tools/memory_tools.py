"""Memory tools: let the model read, save, and delete memdir entries."""
from __future__ import annotations

from typing import Any, ClassVar

from .. import memdir
from ..memdir import VALID_TYPES, Memory
from .base import PermissionDecision, Tool, ToolContext


class MemorySaveTool(Tool):
    name: ClassVar[str] = "MemorySave"
    description: ClassVar[str] = (
        "Store a long-term memory that will be auto-loaded at the start of "
        "every future session in this workspace. Use this when the user "
        "reveals stable preferences, project goals, or facts worth remembering "
        "across conversations. Each memory has: name (short title), "
        "description (one-line hook for relevance matching), type "
        "(user/feedback/project/reference), and body (the memory content). "
        "Do NOT use for ephemeral task state — use TodoWrite for that."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Short human-readable memory title."},
            "description": {"type": "string", "description": "One-line hook explaining when this memory is relevant."},
            "type": {
                "type": "string",
                "enum": list(VALID_TYPES),
                "description": "Memory category.",
            },
            "body": {"type": "string", "description": "Full memory content (markdown)."},
        },
        "required": ["name", "description", "type", "body"],
    }
    is_read_only: ClassVar[bool] = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        name = (input.get("name") or "").strip()
        description = (input.get("description") or "").strip()
        mem_type = (input.get("type") or "reference").strip()
        body = (input.get("body") or "").strip()
        if not name:
            return "error: name is required"
        if not body:
            return "error: body is required"
        if mem_type not in VALID_TYPES:
            return f"error: type must be one of {VALID_TYPES}"
        mem = Memory(name=name, description=description, type=mem_type, body=body)  # type: ignore[arg-type]
        saved = memdir.save_memory(ctx.session.cwd, mem)
        return f"saved memory '{saved.name}' → {saved.path}"


class MemoryListTool(Tool):
    name: ClassVar[str] = "MemoryList"
    description: ClassVar[str] = (
        "List all stored memories for the current workspace with their names, "
        "types, and descriptions."
    )
    input_schema: ClassVar[dict[str, Any]] = {"type": "object", "properties": {}}
    is_read_only: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        mems = memdir.list_memories(ctx.session.cwd)
        if not mems:
            return "(no memories stored in this workspace)"
        lines = [f"{len(mems)} memories:"]
        for m in mems:
            lines.append(f"  [{m.type}] {m.name} — {m.description}")
        return "\n".join(lines)


class MemoryDeleteTool(Tool):
    name: ClassVar[str] = "MemoryDelete"
    description: ClassVar[str] = (
        "Delete a stored memory by name. Use when a memory is outdated or wrong."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Memory name to delete."},
        },
        "required": ["name"],
    }
    is_read_only: ClassVar[bool] = False
    is_destructive: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="ask")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        name = (input.get("name") or "").strip()
        if not name:
            return "error: name is required"
        ok = memdir.delete_memory(ctx.session.cwd, name)
        return f"deleted memory '{name}'" if ok else f"no memory named '{name}'"
