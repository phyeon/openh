"""Grep tool — search file contents using ripgrep, falling back to Python re."""
from __future__ import annotations

import asyncio
import bisect
import re
import shutil
from pathlib import Path
from typing import Any, ClassVar

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext

MAX_OUTPUT_BYTES = 50_000
DEFAULT_HEAD_LIMIT = 250
_IGNORED_NAMES = {"node_modules", "target", "__pycache__", ".git"}


def _extensions_for_type(file_type: str) -> list[str]:
    mapping = {
        "rust": ["rs"],
        "rs": ["rs"],
        "js": ["js", "jsx", "mjs", "cjs"],
        "ts": ["ts", "tsx", "mts", "cts"],
        "py": ["py", "pyi"],
        "python": ["py", "pyi"],
        "go": ["go"],
        "java": ["java"],
        "c": ["c", "h"],
        "cpp": ["cpp", "hpp", "cc", "hh", "cxx"],
        "swift": ["swift"],
        "kt": ["kt", "kts"],
        "kotlin": ["kt", "kts"],
        "json": ["json"],
        "yaml": ["yaml", "yml"],
        "yml": ["yaml", "yml"],
        "toml": ["toml"],
        "md": ["md", "markdown"],
        "markdown": ["md", "markdown"],
        "sh": ["sh", "bash", "zsh"],
        "bash": ["sh", "bash", "zsh"],
    }
    return mapping.get((file_type or "").lower(), [])


class GrepTool(Tool):
    name: ClassVar[str] = "Grep"
    permission_level = PermissionLevel.READ_ONLY
    description: ClassVar[str] = (
        "A powerful search tool built on ripgrep. Supports full regex syntax. "
        "Filter files with the glob parameter or the type parameter. "
        "Output modes: 'content' shows matching lines, "
        "'files_with_matches' shows only file paths (default), 'count' shows match counts. "
        "ALWAYS use Grep for content search. NEVER invoke grep or rg via Bash."
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
            "type": {
                "type": "string",
                "description": "Optional file type shorthand like py, ts, js, rust, go, json, yaml.",
            },
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
                "description": "Output mode. Defaults to `files_with_matches`.",
            },
            "case_insensitive": {"type": "boolean", "description": "Case-insensitive search."},
            "-i": {"type": "boolean", "description": "Case-insensitive search."},
            "-n": {
                "type": "boolean",
                "description": "Show line numbers in content mode. Defaults to true.",
            },
            "context": {
                "type": "integer",
                "description": "Number of context lines to show before and after each match.",
            },
            "multiline": {
                "type": "boolean",
                "description": "Enable multiline regex mode where matches can span newlines.",
            },
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
        file_type = input.get("type")
        output_mode = input.get("output_mode") or "files_with_matches"
        case_insensitive = bool(input.get("case_insensitive") or input.get("-i"))
        show_line_numbers_raw = input.get("-n")
        show_line_numbers = True if show_line_numbers_raw is None else bool(show_line_numbers_raw)
        context_lines = max(0, int(input.get("context") or 0))
        multiline = bool(input.get("multiline"))
        head_limit = int(input.get("head_limit") or DEFAULT_HEAD_LIMIT)
        extensions = _extensions_for_type(str(file_type or ""))

        if shutil.which("rg"):
            return await self._run_rg(
                pattern,
                path,
                glob_pattern,
                output_mode,
                case_insensitive,
                show_line_numbers,
                context_lines,
                multiline,
                head_limit,
                extensions,
            )
        return self._run_python(
            pattern,
            path,
            glob_pattern,
            output_mode,
            case_insensitive,
            show_line_numbers,
            context_lines,
            multiline,
            head_limit,
            extensions,
        )

    @staticmethod
    async def _run_rg(
        pattern: str,
        path: str,
        glob_pattern: str | None,
        output_mode: str,
        case_insensitive: bool,
        show_line_numbers: bool,
        context_lines: int,
        multiline: bool,
        head_limit: int,
        extensions: list[str],
    ) -> str:
        args = ["rg"]
        if case_insensitive:
            args.append("-i")
        if multiline:
            args.append("--multiline")
        if output_mode == "files_with_matches":
            args.append("-l")
        elif output_mode == "count":
            args.append("-c")
        else:
            if show_line_numbers:
                args.append("-n")
            else:
                args.append("--no-line-number")
            args.extend(["--column", "--no-heading"])
            if context_lines > 0:
                args.extend(["-C", str(context_lines)])
        if glob_pattern:
            args.extend(["-g", glob_pattern])
        for ext in extensions:
            args.extend(["-g", f"*.{ext}"])
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
        show_line_numbers: bool,
        context_lines: int,
        multiline: bool,
        head_limit: int,
        extensions: list[str],
    ) -> str:
        flags = re.IGNORECASE if case_insensitive else 0
        if multiline:
            flags |= re.MULTILINE | re.DOTALL
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
            if any(part.startswith(".") or part in _IGNORED_NAMES for part in f.parts):
                continue
            if extensions:
                ext = f.suffix.lstrip(".").lower()
                if ext not in extensions:
                    continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            lines = content.splitlines()
            if multiline:
                matches = list(regex.finditer(content))
                if not matches:
                    continue
                match_files[str(f)] = len(matches)
                if output_mode == "content":
                    rendered = _render_multiline_matches(
                        f,
                        content,
                        lines,
                        matches,
                        context_lines=context_lines,
                        show_line_numbers=show_line_numbers,
                    )
                    for line in rendered:
                        out.append(line)
                        if len(out) >= head_limit:
                            break
            else:
                match_lines: list[int] = []
                for n, line in enumerate(lines, start=1):
                    if regex.search(line):
                        match_lines.append(n)
                if not match_lines:
                    continue
                match_files[str(f)] = len(match_lines)
                if output_mode == "content":
                    rendered = _render_line_matches(
                        f,
                        lines,
                        match_lines,
                        context_lines=context_lines,
                        show_line_numbers=show_line_numbers,
                    )
                    for line in rendered:
                        out.append(line)
                        if len(out) >= head_limit:
                            break

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


def _render_line_matches(
    path: Path,
    lines: list[str],
    match_lines: list[int],
    *,
    context_lines: int,
    show_line_numbers: bool,
) -> list[str]:
    selected = _expand_with_context(match_lines, len(lines), context_lines)
    return _format_selected_lines(path, lines, selected, show_line_numbers=show_line_numbers)


def _render_multiline_matches(
    path: Path,
    content: str,
    lines: list[str],
    matches: list[re.Match[str]],
    *,
    context_lines: int,
    show_line_numbers: bool,
) -> list[str]:
    if not lines:
        return []

    offsets = [0]
    for idx, char in enumerate(content):
        if char == "\n":
            offsets.append(idx + 1)

    matched_lines: list[int] = []
    for match in matches:
        start_line = bisect.bisect_right(offsets, match.start())
        end_pos = max(match.start(), match.end() - 1)
        end_line = bisect.bisect_right(offsets, end_pos)
        matched_lines.extend(range(start_line, end_line + 1))

    selected = _expand_with_context(matched_lines, len(lines), context_lines)
    return _format_selected_lines(path, lines, selected, show_line_numbers=show_line_numbers)


def _expand_with_context(match_lines: list[int], total_lines: int, context_lines: int) -> list[int]:
    selected: set[int] = set()
    for line_no in match_lines:
        start = max(1, line_no - context_lines)
        end = min(total_lines, line_no + context_lines)
        selected.update(range(start, end + 1))
    return sorted(selected)


def _format_selected_lines(
    path: Path,
    lines: list[str],
    selected_lines: list[int],
    *,
    show_line_numbers: bool,
) -> list[str]:
    output: list[str] = []
    prev_line = 0
    for line_no in selected_lines:
        if prev_line and line_no > prev_line + 1:
            output.append("--")
        line_text = lines[line_no - 1]
        if show_line_numbers:
            output.append(f"{path}:{line_no}:{line_text}")
        else:
            output.append(f"{path}:{line_text}")
        prev_line = line_no
    return output
