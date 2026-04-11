"""Write tool — create or fully overwrite a file."""
from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from .base import PermissionDecision, Tool, ToolContext


class WriteTool(Tool):
    name: ClassVar[str] = "Write"
    description: ClassVar[str] = (
        "Writes a file to the local filesystem. This tool will overwrite the existing "
        "file if there is one at the provided path. If this is an existing file, you MUST "
        "use the Read tool first. Prefer the Edit tool for modifying existing files — "
        "it only sends the diff. Only use Write to create new files or for complete rewrites."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file."},
            "content": {"type": "string", "description": "Full file contents."},
        },
        "required": ["file_path", "content"],
    }
    is_destructive: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        if ("Write", "*") in ctx.session.always_allow:
            return PermissionDecision(behavior="allow")
        return PermissionDecision(behavior="ask")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        file_path = input.get("file_path")
        content = input.get("content")
        if not file_path:
            return "error: file_path is required"
        if content is None:
            return "error: content is required"
        path = Path(file_path)
        if not path.is_absolute():
            return f"error: file_path must be absolute, got: {file_path}"

        if path.exists():
            resolved = str(path.resolve())
            if resolved not in ctx.session.read_files:
                return (
                    f"error: file already exists at {file_path} but was not Read in this session. "
                    "Use Read first, then Write."
                )

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"error: write failed: {exc}"

        ctx.session.read_files.add(str(path.resolve()))
        return f"wrote {len(content)} chars to {path}"
