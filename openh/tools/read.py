"""Read tool — read text from a file with line numbers."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext

MAX_BYTES = 1024 * 1024  # 1 MiB cap for safety
DEFAULT_LIMIT = 2000
MAX_RESULT_CHARS = 40_000  # ~10K tokens, matches Claude Code harness truncation


class ReadTool(Tool):
    name: ClassVar[str] = "Read"
    permission_level = PermissionLevel.READ_ONLY
    description: ClassVar[str] = (
        "Reads a file from the local filesystem. The file_path must be absolute. "
        "By default, it reads up to 2000 lines starting from the beginning of the file. "
        "When you already know which part of the file you need, only read that part — "
        "this can be important for larger files. Results are returned with line numbers "
        "starting at 1. Always read a file before editing it."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file."},
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (1-indexed). Optional.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read. Optional.",
            },
        },
        "required": ["file_path"],
    }
    is_read_only: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        file_path = input.get("file_path")
        if not file_path:
            return "error: file_path is required"
        path = Path(file_path)
        if not path.is_absolute():
            return f"error: file_path must be absolute, got: {file_path}"
        if not path.exists():
            return f"error: file does not exist: {file_path}"
        if path.is_dir():
            return f"error: path is a directory, not a file: {file_path}"

        try:
            size = path.stat().st_size
        except OSError as exc:
            return f"error: stat failed: {exc}"
        if size > MAX_BYTES:
            return f"error: file is {size} bytes, exceeds {MAX_BYTES} byte limit"

        offset = int(input.get("offset") or 1)
        limit = int(input.get("limit") or DEFAULT_LIMIT)
        if offset < 1:
            offset = 1
        if limit < 1:
            limit = DEFAULT_LIMIT

        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError as exc:
            return f"error: read failed: {exc}"

        total = len(lines)
        start = offset - 1
        end = min(start + limit, total)
        slice_ = lines[start:end]

        ctx.session.read_files.add(str(path.resolve()))

        out: list[str] = []
        for i, line in enumerate(slice_, start=offset):
            out.append(f"{i:6d}\t{line.rstrip(chr(10))}")

        header = f"# {path} ({total} lines, showing {offset}-{end})\n" if total > limit else ""
        result = header + "\n".join(out)
        if len(result) > MAX_RESULT_CHARS:
            result = result[:MAX_RESULT_CHARS] + f"\n\n…(truncated at {MAX_RESULT_CHARS} chars. Use offset/limit to read specific sections.)"
        return result
