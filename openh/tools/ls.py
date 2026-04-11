"""LS tool — list directory contents."""
from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from .base import PermissionDecision, Tool, ToolContext


class LSTool(Tool):
    name: ClassVar[str] = "LS"
    description: ClassVar[str] = (
        "List the contents of a directory (files and subdirectories). "
        "Returns up to 200 entries sorted alphabetically, with a trailing / on directories. "
        "The `path` must be absolute."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute path of the directory to list.",
            },
            "ignore": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Glob patterns to exclude from the listing.",
            },
        },
        "required": ["path"],
    }
    is_read_only: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        raw = input.get("path")
        if not raw:
            return "error: path is required"
        path = Path(raw)
        if not path.is_absolute():
            return f"error: path must be absolute, got: {raw}"
        if not path.exists():
            return f"error: path does not exist: {raw}"
        if not path.is_dir():
            return f"error: path is not a directory: {raw}"

        ignore = input.get("ignore") or []
        import fnmatch

        entries: list[str] = []
        try:
            for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
                name = child.name
                if any(fnmatch.fnmatch(name, pat) for pat in ignore):
                    continue
                if child.is_dir():
                    entries.append(name + "/")
                else:
                    entries.append(name)
                if len(entries) >= 200:
                    entries.append(f"… (truncated at 200 entries)")
                    break
        except OSError as exc:
            return f"error: {exc}"

        if not entries:
            return f"{path} is empty"
        return f"{path}\n" + "\n".join(f"  {e}" for e in entries)
