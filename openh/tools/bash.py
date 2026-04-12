"""Bash tool — execute shell commands with optional background mode."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .base import PermissionDecision, Tool, ToolContext

DEFAULT_TIMEOUT = 120
MAX_OUTPUT_BYTES = 30_000

_BG_SHELLS: dict[str, "BackgroundShell"] = {}


@dataclass
class BackgroundShell:
    shell_id: str
    command: str
    description: str
    process: asyncio.subprocess.Process
    stdout_buffer: list[str] = field(default_factory=list)
    stderr_buffer: list[str] = field(default_factory=list)
    stdout_offset: int = 0
    stderr_offset: int = 0
    done: bool = False
    exit_code: int | None = None
    _reader_task: "asyncio.Task | None" = None


class BashTool(Tool):
    name: ClassVar[str] = "Bash"
    description: ClassVar[str] = (
        "Executes a given bash command and returns its output. "
        "IMPORTANT: Avoid using this tool to run cat, head, tail, sed, awk, grep, or find "
        "— use the dedicated Read, Edit, Glob, and Grep tools instead. "
        "The working directory persists between commands, but shell state does not. "
        "Default timeout 2 minutes. Set run_in_background=true to start the command "
        "in the background. Always quote file paths that contain spaces."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute."},
            "description": {
                "type": "string",
                "description": "Short description of what the command does.",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (foreground only). Defaults to 120.",
            },
            "run_in_background": {
                "type": "boolean",
                "description": "Start in background; returns immediately with shell_id.",
            },
        },
        "required": ["command"],
    }
    is_destructive: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        if ("Bash", "*") in ctx.session.always_allow:
            return PermissionDecision(behavior="allow")
        return PermissionDecision(behavior="ask")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        command = input.get("command")
        if not command:
            return "error: command is required"
        background = bool(input.get("run_in_background"))
        description = (input.get("description") or "").strip()

        if background:
            return await self._run_background(command, description, ctx)
        return await self._run_foreground(command, input, ctx)

    async def _run_foreground(
        self, command: str, input: dict[str, Any], ctx: ToolContext
    ) -> str:
        timeout = int(input.get("timeout") or DEFAULT_TIMEOUT)
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=ctx.session.cwd,
            )
        except OSError as exc:
            return f"error: failed to start: {exc}"

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass
            return f"error: command timed out after {timeout}s"

        stdout = _truncate(stdout_b.decode("utf-8", errors="replace"))
        stderr = _truncate(stderr_b.decode("utf-8", errors="replace"))
        rc = proc.returncode

        out_lines = [f"exit_code: {rc}"]
        if stdout:
            out_lines.append("stdout:")
            out_lines.append(stdout)
        if stderr:
            out_lines.append("stderr:")
            out_lines.append(stderr)
        if not stdout and not stderr:
            out_lines.append("(no output)")
        return "\n".join(out_lines)

    async def _run_background(
        self, command: str, description: str, ctx: ToolContext
    ) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=ctx.session.cwd,
            )
        except OSError as exc:
            return f"error: failed to start: {exc}"

        shell_id = f"bash_{uuid.uuid4().hex[:8]}"
        shell = BackgroundShell(
            shell_id=shell_id,
            command=command,
            description=description,
            process=proc,
        )
        _BG_SHELLS[shell_id] = shell
        shell._reader_task = asyncio.create_task(_drain(shell))
        return (
            f"started background shell {shell_id}\n"
            f"command: {command}\n"
            "use BashOutput to poll, KillShell to stop."
        )


async def _drain(shell: BackgroundShell) -> None:
    proc = shell.process
    assert proc.stdout is not None
    assert proc.stderr is not None

    async def _read_stream(stream, buf: list[str]) -> None:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            buf.append(chunk.decode("utf-8", errors="replace"))

    try:
        await asyncio.gather(
            _read_stream(proc.stdout, shell.stdout_buffer),
            _read_stream(proc.stderr, shell.stderr_buffer),
        )
    finally:
        shell.exit_code = await proc.wait()
        shell.done = True


import re

# ANSI escape sequences: CSI (ESC[...), OSC (ESC]...), and single ESC+char
_ANSI_RE = re.compile(r"""
    \x1b       # ESC
    (?:
        \[     # CSI
        [0-9;?]*  # params
        [A-Za-z]  # final byte
    |
        \]     # OSC
        .*?    # payload
        (?:\x07|\x1b\\)  # ST
    |
        [()][AB012]  # charset select
    |
        [=>Nno|~}]   # misc single-char
    )
""", re.VERBOSE)

# Cursor movement / screen control that produce no visible content
_JUNK_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences and control chars (like Claude Code does)."""
    text = _ANSI_RE.sub("", text)
    text = _JUNK_RE.sub("", text)
    # Collapse runs of blank lines
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text


def _truncate(text: str) -> str:
    text = _strip_ansi(text)
    if len(text) <= MAX_OUTPUT_BYTES:
        return text
    # Keep first and last portions for context
    head = MAX_OUTPUT_BYTES * 3 // 4
    tail = MAX_OUTPUT_BYTES // 4
    return (
        text[:head]
        + f"\n\n… ({len(text) - MAX_OUTPUT_BYTES:,} chars truncated) …\n\n"
        + text[-tail:]
    )


class BashOutputTool(Tool):
    name: ClassVar[str] = "BashOutput"
    description: ClassVar[str] = (
        "Retrieve the latest stdout/stderr from a background shell started with "
        "`Bash(run_in_background=true)`. Returns only the new output since the "
        "last poll. Also reports whether the shell has exited and its exit code."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "shell_id": {"type": "string", "description": "ID returned by Bash."},
        },
        "required": ["shell_id"],
    }
    is_read_only: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        shell_id = input.get("shell_id", "")
        shell = _BG_SHELLS.get(shell_id)
        if shell is None:
            return f"error: no shell with id {shell_id}"

        combined_stdout = "".join(shell.stdout_buffer)
        combined_stderr = "".join(shell.stderr_buffer)
        new_stdout = combined_stdout[shell.stdout_offset:]
        new_stderr = combined_stderr[shell.stderr_offset:]
        shell.stdout_offset = len(combined_stdout)
        shell.stderr_offset = len(combined_stderr)

        parts = [
            f"shell_id: {shell_id}",
            f"status: {'exited' if shell.done else 'running'}",
        ]
        if shell.done and shell.exit_code is not None:
            parts.append(f"exit_code: {shell.exit_code}")
        if new_stdout:
            parts.append("stdout:")
            parts.append(_truncate(new_stdout))
        if new_stderr:
            parts.append("stderr:")
            parts.append(_truncate(new_stderr))
        if not new_stdout and not new_stderr:
            parts.append("(no new output)")
        return "\n".join(parts)


class KillShellTool(Tool):
    name: ClassVar[str] = "KillShell"
    description: ClassVar[str] = (
        "Terminate a background shell started by Bash. Kills the process "
        "and removes the shell from the registry."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "shell_id": {"type": "string", "description": "ID returned by Bash."},
        },
        "required": ["shell_id"],
    }
    is_destructive: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        if ("KillShell", "*") in ctx.session.always_allow:
            return PermissionDecision(behavior="allow")
        return PermissionDecision(behavior="ask")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        shell_id = input.get("shell_id", "")
        shell = _BG_SHELLS.get(shell_id)
        if shell is None:
            return f"error: no shell with id {shell_id}"
        try:
            shell.process.kill()
            await shell.process.wait()
        except Exception as exc:  # noqa: BLE001
            return f"error: kill failed: {exc}"
        _BG_SHELLS.pop(shell_id, None)
        return f"killed {shell_id}"
