"""Bash tool — execute shell commands with optional background mode.

CC-aligned implementation:
- stdin=DEVNULL to prevent hangs
- Sentinel-based cwd + env var tracking across invocations
- ANSI escape stripping for ncurses/interactive output
- Output truncation at 100K chars with 50/50 head/tail split
- Timeout cap at 600s (10 min)
- notify_on_complete for background tasks
"""
from __future__ import annotations

import asyncio
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

from .base import PermissionDecision, Tool, ToolContext

DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600  # 10 minutes hard cap (CC pattern)
MAX_OUTPUT_CHARS = 100_000  # CC uses 100K

_BG_SHELLS: dict[str, "BackgroundShell"] = {}

# Completion callbacks: shell_id -> coroutine to call with summary
_COMPLETION_CALLBACKS: dict[str, Any] = {}


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


# ---------------------------------------------------------------------------
#  ANSI stripping
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"""
    \x1b
    (?:
        \[ [0-9;?]* [A-Za-z]
    |   \] .*? (?:\x07|\x1b\\)
    |   [()][AB012]
    |   [=>Nno|~}]
    )
""", re.VERBOSE)

_JUNK_RE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")


def _strip_ansi(text: str) -> str:
    text = _ANSI_RE.sub("", text)
    text = _JUNK_RE.sub("", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text


def _truncate(text: str) -> str:
    text = _strip_ansi(text)
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    half = MAX_OUTPUT_CHARS // 2
    return (
        text[:half]
        + f"\n\n… ({len(text) - MAX_OUTPUT_CHARS:,} chars truncated) …\n\n"
        + text[-half:]
    )


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


# Env vars to skip when persisting (CC pattern)
_SKIP_ENV = frozenset({
    "SHLVL", "BASH_LINENO", "BASH_SOURCE", "FUNCNAME",
    "PIPESTATUS", "OLDPWD", "PWD", "SHELL", "HOME",
    "USER", "LOGNAME", "PATH", "TERM", "LANG", "LC_ALL",
    "TMPDIR", "DISPLAY", "SSH_AUTH_SOCK", "XPC_FLAGS",
    "XPC_SERVICE_NAME", "COLORTERM", "TERM_PROGRAM",
    "TERM_PROGRAM_VERSION", "ITERM_SESSION_ID",
    "__openh_rc", "_",
})


# ---------------------------------------------------------------------------
#  BashTool
# ---------------------------------------------------------------------------

class BashTool(Tool):
    name: ClassVar[str] = "Bash"
    description: ClassVar[str] = (
        "Executes a given bash command and returns its output. "
        "IMPORTANT: Avoid using this tool to run cat, head, tail, sed, awk, grep, or find "
        "— use the dedicated Read, Edit, Glob, and Grep tools instead. "
        "The working directory and environment variables persist between commands. "
        "Default timeout 2 minutes (max 10 minutes). "
        "Set run_in_background=true to start the command in the background. "
        "Always quote file paths that contain spaces."
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
                "description": "Timeout in seconds (foreground only). Default 120, max 600.",
            },
            "run_in_background": {
                "type": "boolean",
                "description": "Start in background; returns immediately with shell_id.",
            },
            "use_pty": {
                "type": "boolean",
                "description": "Run in a pseudo-terminal (for programs that need a TTY like npm, cargo, pytest).",
            },
        },
        "required": ["command"],
    }
    is_destructive: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        from .bash_classifier import classify, RiskLevel

        command = input.get("command", "")
        level = classify(command)

        # Critical → unconditionally blocked (CC pattern)
        if level == RiskLevel.CRITICAL:
            return PermissionDecision(
                behavior="deny",
                reason=f"BLOCKED: critical-risk command detected",
            )

        # Always-allow only covers Safe + Low
        if ("Bash", "*") in ctx.session.always_allow:
            if level <= RiskLevel.LOW:
                return PermissionDecision(behavior="allow")
            # Medium/High still need explicit permission even with always_allow
            return PermissionDecision(behavior="ask")

        return PermissionDecision(behavior="ask")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        command = input.get("command")
        if not command:
            return "error: command is required"
        background = bool(input.get("run_in_background"))
        description = (input.get("description") or "").strip()

        if background:
            return await self._run_background(command, description, ctx)
        if bool(input.get("use_pty")):
            return await self._run_pty(command, input, ctx)
        return await self._run_foreground(command, input, ctx)

    async def _run_foreground(
        self, command: str, input: dict[str, Any], ctx: ToolContext
    ) -> str:
        timeout = min(int(input.get("timeout") or DEFAULT_TIMEOUT), MAX_TIMEOUT)

        # CC sentinel pattern: restore env, run command, capture cwd+env
        sentinel = "__OPENH_STATE__"
        env_restore = ""
        for k, v in getattr(ctx.session, "shell_env", {}).items():
            env_restore += f"export {k}={_shell_quote(v)}\n"
        wrapped = (
            f"cd {_shell_quote(ctx.session.cwd)} 2>/dev/null\n"
            f"{env_restore}"
            f"{command}\n"
            f"__openh_rc=$?\n"
            f"echo\necho '{sentinel}'\npwd\nenv\n"
            f"exit $__openh_rc"
        )
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", wrapped,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=ctx.session.cwd,
            )
        except OSError as exc:
            return f"error: failed to start: {exc}"

        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass
            return f"error: command timed out after {timeout}s"

        raw_stdout = stdout_b.decode("utf-8", errors="replace")
        stderr_text = _truncate(stderr_b.decode("utf-8", errors="replace"))
        rc = proc.returncode

        # Extract cwd + env from sentinel
        stdout_text = raw_stdout
        if sentinel in raw_stdout:
            parts = raw_stdout.rsplit(sentinel, 1)
            stdout_text = parts[0]
            state_lines = parts[1].strip().splitlines()
            if state_lines:
                new_cwd = state_lines[0].strip()
                if os.path.isdir(new_cwd):
                    ctx.session.cwd = new_cwd
                # Parse env vars
                if hasattr(ctx.session, "shell_env"):
                    new_env: dict[str, str] = {}
                    for line in state_lines[1:]:
                        if "=" not in line:
                            continue
                        k, _, v = line.partition("=")
                        if k.startswith("_") or k in _SKIP_ENV:
                            continue
                        new_env[k] = v
                    inherited = os.environ
                    for k, v in new_env.items():
                        if k not in inherited or inherited[k] != v:
                            ctx.session.shell_env[k] = v

        stdout_text = _truncate(stdout_text)

        out_lines = [f"exit_code: {rc}"]
        if stdout_text:
            out_lines.append("stdout:")
            out_lines.append(stdout_text)
        if stderr_text:
            out_lines.append("stderr:")
            out_lines.append(stderr_text)
        if not stdout_text and not stderr_text:
            out_lines.append("(no output)")
        return "\n".join(out_lines)

    async def _run_pty(
        self, command: str, input: dict[str, Any], ctx: ToolContext
    ) -> str:
        """Run command in a pseudo-terminal (CC pty_bash.rs pattern).

        Programs that check isatty() (npm, cargo, pytest, git) will see a real
        TTY and produce their normal interactive output. Output is ANSI-stripped.
        """
        import pty as _pty
        import struct
        import termios
        import fcntl

        timeout = min(int(input.get("timeout") or DEFAULT_TIMEOUT), MAX_TIMEOUT)
        max_bytes = 2 * 1024 * 1024  # 2 MB raw cap (CC pattern)

        # Create PTY pair
        master_fd, slave_fd = _pty.openpty()

        # Set PTY size: 50 rows x 220 cols (CC pattern)
        winsize = struct.pack("HHHH", 50, 220, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        loop = asyncio.get_event_loop()

        try:
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", command,
                stdout=slave_fd,
                stderr=slave_fd,
                stdin=asyncio.subprocess.DEVNULL,
                cwd=ctx.session.cwd,
                close_fds=True,
            )
        except OSError as exc:
            os.close(master_fd)
            os.close(slave_fd)
            return f"error: failed to start: {exc}"

        os.close(slave_fd)  # parent doesn't need slave

        # Read from master_fd with timeout
        output_chunks: list[bytes] = []
        total_bytes = 0

        async def _read_pty():
            nonlocal total_bytes
            while True:
                try:
                    chunk = await loop.run_in_executor(
                        None, lambda: os.read(master_fd, 4096)
                    )
                except OSError:
                    break
                if not chunk:
                    break
                output_chunks.append(chunk)
                total_bytes += len(chunk)
                if total_bytes >= max_bytes:
                    break

        try:
            await asyncio.wait_for(_read_pty(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass
            os.close(master_fd)
            raw = b"".join(output_chunks).decode("utf-8", errors="replace")
            return f"error: command timed out after {timeout}s\n{_truncate(raw)}"

        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()

        os.close(master_fd)
        rc = proc.returncode or 0

        raw = b"".join(output_chunks).decode("utf-8", errors="replace")
        cleaned = _truncate(raw)

        out_lines = [f"exit_code: {rc}"]
        if cleaned:
            out_lines.append("output:")
            out_lines.append(cleaned)
        else:
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
                stdin=asyncio.subprocess.DEVNULL,
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


# ---------------------------------------------------------------------------
#  Background shell drain + notify
# ---------------------------------------------------------------------------

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
        # notify_on_complete (CC pattern)
        cb = _COMPLETION_CALLBACKS.pop(shell.shell_id, None)
        if cb is not None:
            try:
                combined = "".join(shell.stdout_buffer) + "".join(shell.stderr_buffer)
                summary = _truncate(combined[-2000:])  # last 2000 chars (CC uses this)
                await cb(shell.shell_id, shell.exit_code, summary)
            except Exception:
                pass


def register_completion_callback(shell_id: str, callback) -> None:
    """Register a coroutine to be called when a background shell completes.

    callback signature: async def cb(shell_id: str, exit_code: int, summary: str)
    """
    _COMPLETION_CALLBACKS[shell_id] = callback


# ---------------------------------------------------------------------------
#  BashOutputTool
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
#  KillShellTool
# ---------------------------------------------------------------------------

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
        _COMPLETION_CALLBACKS.pop(shell_id, None)
        return f"killed {shell_id}"
