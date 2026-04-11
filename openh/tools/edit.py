"""Edit tool — exact-string replacement in an existing file."""
from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from .base import PermissionDecision, Tool, ToolContext


class EditTool(Tool):
    name: ClassVar[str] = "Edit"
    description: ClassVar[str] = (
        "Replace one exact substring in an existing file. "
        "The target file must have been Read in this session first. "
        "By default, `old_string` must appear exactly once; set `replace_all=True` "
        "to replace every occurrence. Always requires the user's permission."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file."},
            "old_string": {"type": "string", "description": "Exact substring to replace."},
            "new_string": {"type": "string", "description": "Replacement substring."},
            "replace_all": {
                "type": "boolean",
                "description": "Replace every occurrence instead of requiring a unique match.",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    }
    is_destructive: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        if ("Edit", "*") in ctx.session.always_allow:
            return PermissionDecision(behavior="allow")
        return PermissionDecision(behavior="ask")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        file_path = input.get("file_path")
        old = input.get("old_string")
        new = input.get("new_string")
        replace_all = bool(input.get("replace_all"))
        if not file_path:
            return "error: file_path is required"
        if old is None or new is None:
            return "error: old_string and new_string are required"
        if old == new:
            return "error: old_string and new_string are identical"

        path = Path(file_path)
        if not path.is_absolute():
            return f"error: file_path must be absolute, got: {file_path}"
        if not path.exists():
            return f"error: file does not exist: {file_path}"

        resolved = str(path.resolve())
        if resolved not in ctx.session.read_files:
            return (
                f"error: file {file_path} must be Read in this session before Edit. "
                "Use Read first."
            )

        try:
            current = path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"error: read failed: {exc}"

        count = current.count(old)
        if count == 0:
            return f"error: old_string not found in {file_path}"
        if count > 1 and not replace_all:
            return (
                f"error: old_string appears {count} times in {file_path}. "
                "Provide more surrounding context to make it unique, or set replace_all=True."
            )

        new_text = current.replace(old, new) if replace_all else current.replace(old, new, 1)

        try:
            path.write_text(new_text, encoding="utf-8")
        except OSError as exc:
            return f"error: write failed: {exc}"

        # Re-register so subsequent edits stay valid
        ctx.session.read_files.add(resolved)
        return f"edited {path} ({count} replacement{'s' if count != 1 else ''})"
