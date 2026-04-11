"""Grep tool — search file contents using ripgrep, falling back to Python re."""
from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any, ClassVar

from .base import PermissionDecision, Tool, ToolContext

MAX_OUTPUT_BYTES = 50_000
DEFAULT_HEAD_LIMIT = 250


class GrepTool(Tool):
    name: ClassVar[str] = "Grep"
    description: ClassVar[str] = (
        "Search for a regex pattern across file contents. Backed by ripgrep when available, "
        "with a Python fallback. Returns matching lines (default), or just file paths "
        "(`output_mode='files_with_matches'`), or counts (`output_mode='count'`)."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression to search for."},
            "path": {
                "type": "string",
                "description": "File or directory to search. Optional, defaults to cwd.",
            },
            "glob": {
                "type": "string",
                "description": "Glob filter for which files to include (e.g. `*.py`). Optional.",
            },
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "description": "Output mode. Defaults to `content`.",
            },
            "case_insensitive": {"type": "boolean", "description": "Case-insensitive search."},
            "head_limit": {
                "type": "integer",
                "description": "Max lines/entries to return. Defaults to 250.",
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
        path = input.get("path") or ctx.session.cwd
        glob_pattern = input.get("glob")
        output_mode = input.get("output_mode") or "content"
        case_insensitive = bool(input.get("case_insensitive"))
        head_limit = int(input.get("head_limit") or DEFAULT_HEAD_LIMIT)

        if shutil.which("rg"):
            return await self._run_rg(
                pattern, path, glob_pattern, output_mode, case_insensitive, head_limit
            )
        return self._run_python(
            pattern, path, glob_pattern, output_mode, case_insensitive, head_limit
        )

    @staticmethod
    async def _run_rg(
        pattern: str,
        path: str,
        glob_pattern: str | None,
        output_mode: str,
        case_insensitive: bool,
        head_limit: int,
    ) -> str:
        args = ["rg"]
        if case_insensitive:
            args.append("-i")
        if output_mode == "files_with_matches":
            args.append("-l")
        elif output_mode == "count":
            args.append("-c")
        else:
            args.extend(["-n", "--column", "--no-heading"])
        if glob_pattern:
            args.extend(["-g", glob_pattern])
        args.extend(["--", pattern, path])

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except OSError as exc:
            return f"error: rg failed to start: {exc}"

        if proc.returncode not in (0, 1):  # 1 = no match
            err = stderr.decode("utf-8", errors="replace").strip()
            return f"error: rg exited {proc.returncode}: {err}"

        text = stdout.decode("utf-8", errors="replace")
        lines = text.splitlines()
        if len(lines) > head_limit:
            lines = lines[:head_limit] + [f"… (truncated, {len(text.splitlines()) - head_limit} more)"]
        result = "\n".join(lines)
        if not result:
            return "no matches"
        if len(result) > MAX_OUTPUT_BYTES:
            result = result[:MAX_OUTPUT_BYTES] + "\n… (truncated by byte limit)"
        return result

    @staticmethod
    def _run_python(
        pattern: str,
        path: str,
        glob_pattern: str | None,
        output_mode: str,
        case_insensitive: bool,
        head_limit: int,
    ) -> str:
        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as exc:
            return f"error: invalid regex: {exc}"

        base = Path(path)
        if base.is_file():
            files = [base]
        elif base.is_dir():
            iterator = base.rglob(glob_pattern) if glob_pattern else base.rglob("*")
            files = [p for p in iterator if p.is_file()]
        else:
            return f"error: path does not exist: {path}"

        out: list[str] = []
        match_files: dict[str, int] = {}

        for f in files:
            # skip binaries / huge / hidden git
            if any(part.startswith(".") and part not in (".",) for part in f.parts):
                continue
            try:
                with f.open("r", encoding="utf-8", errors="replace") as fh:
                    for n, line in enumerate(fh, start=1):
                        if regex.search(line):
                            match_files[str(f)] = match_files.get(str(f), 0) + 1
                            if output_mode == "content":
                                out.append(f"{f}:{n}:{line.rstrip(chr(10))}")
                                if len(out) >= head_limit:
                                    break
            except (OSError, UnicodeDecodeError):
                continue
            if output_mode == "content" and len(out) >= head_limit:
                break

        if output_mode == "files_with_matches":
            keys = list(match_files.keys())[:head_limit]
            return "\n".join(keys) if keys else "no matches"
        if output_mode == "count":
            entries = list(match_files.items())[:head_limit]
            return "\n".join(f"{p}:{c}" for p, c in entries) if entries else "no matches"

        if not out:
            return "no matches"
        result = "\n".join(out)
        if len(result) > MAX_OUTPUT_BYTES:
            result = result[:MAX_OUTPUT_BYTES] + "\n… (truncated)"
        return result
