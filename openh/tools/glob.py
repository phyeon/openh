"""Glob tool — find files by pattern."""
from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from .base import PermissionDecision, Tool, ToolContext

MAX_RESULTS = 250


class GlobTool(Tool):
    name: ClassVar[str] = "Glob"
    description: ClassVar[str] = (
        "Fast file pattern matching tool that works with any codebase size. "
        "Supports glob patterns like '**/*.js' or 'src/**/*.ts'. "
        "Returns matching file paths sorted by modification time. "
        "Use this tool when you need to find files by name patterns."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern."},
            "path": {
                "type": "string",
                "description": "Directory to search in. Optional, defaults to cwd.",
            },
        },
        "required": ["pattern"],
    }
    is_read_only: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        pattern = input.get("pattern")
        if not pattern:
            return "error: pattern is required"
        base = Path(input.get("path") or ctx.session.cwd)
        if not base.exists():
            return f"error: path does not exist: {base}"
        if not base.is_dir():
            return f"error: path is not a directory: {base}"

        try:
            matches = list(base.glob(pattern))
        except (ValueError, OSError) as exc:
            return f"error: glob failed: {exc}"

        # Filter to files only and sort by mtime desc
        files = [p for p in matches if p.is_file()]
        try:
            files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            pass

        truncated = files[:MAX_RESULTS]
        if not truncated:
            return f"no files matched {pattern} under {base}"

        out = "\n".join(str(p) for p in truncated)
        suffix = ""
        if len(files) > MAX_RESULTS:
            suffix = f"\n\n... and {len(files) - MAX_RESULTS} more files (showing first {MAX_RESULTS})"
        return out + suffix
