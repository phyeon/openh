"""Worktree tools: create and exit git worktrees for isolated work sessions."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext


@dataclass
class WorktreeSession:
    original_cwd: Path
    worktree_path: Path
    branch: str | None
    original_head: str | None


_WORKTREE_SESSIONS: dict[str, WorktreeSession] = {}


def _session_key(ctx: ToolContext) -> str:
    session_id = getattr(ctx.session, "session_id", "") or ""
    return session_id.strip() or f"session-{id(ctx.session)}"


async def _run_git(cwd: Path, args: list[str]) -> tuple[bool, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        return False, str(exc)

    stdout_b, stderr_b = await proc.communicate()
    stdout = stdout_b.decode("utf-8", errors="replace").strip()
    stderr = stderr_b.decode("utf-8", errors="replace").strip()
    if proc.returncode == 0:
        return True, stdout
    return False, stderr or stdout or f"git exited with {proc.returncode}"


async def _run_shell(command: str, cwd: Path) -> tuple[bool, str]:
    if os.name == "nt":
        argv = ("cmd", "/C", command)
    else:
        argv = ("bash", "-lc", command)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        return False, str(exc)

    stdout_b, stderr_b = await proc.communicate()
    stdout = stdout_b.decode("utf-8", errors="replace").strip()
    stderr = stderr_b.decode("utf-8", errors="replace").strip()
    if proc.returncode == 0:
        return True, stdout
    if stdout and stderr:
        return False, f"{stderr}\n{stdout}"
    return False, stderr or stdout or f"command exited with {proc.returncode}"


def _default_branch_name() -> str:
    now = datetime.now(timezone.utc)
    return f"claurst-{now:%Y%m%d-%H%M%S}"


class EnterWorktreeTool(Tool):
    name: ClassVar[str] = "EnterWorktree"
    permission_level = PermissionLevel.WRITE
    description: ClassVar[str] = (
        "Create a new git worktree and switch the session's working directory to it. "
        "This gives you an isolated environment to experiment or work on a feature "
        "without affecting the main working tree. "
        "Use ExitWorktree to return to the original directory."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "branch": {
                "type": "string",
                "description": (
                    "Branch name to create. Defaults to a timestamped name like "
                    "claurst-20240101-120000."
                ),
            },
            "path": {
                "type": "string",
                "description": (
                    "Optional path for the worktree directory. Defaults to "
                    ".worktrees/<branch>."
                ),
            },
            "post_create_command": {
                "type": "string",
                "description": (
                    "Optional command to run inside the new worktree after creation "
                    "(e.g. 'npm install')."
                ),
            },
        },
    }

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        session_key = _session_key(ctx)
        if session_key in _WORKTREE_SESSIONS:
            return "error: Already in a worktree session. Call ExitWorktree first."

        branch = str(input.get("branch") or input.get("name") or "").strip()
        if not branch:
            branch = _default_branch_name()

        raw_path = str(input.get("path") or "").strip()
        if raw_path:
            worktree_path = ctx.resolve_path(raw_path)
        else:
            worktree_path = Path(ctx.session.cwd) / ".worktrees" / branch
        current_cwd = Path(ctx.session.cwd)

        ok, head_output = await _run_git(current_cwd, ["rev-parse", "HEAD"])
        original_head = head_output.strip() if ok and head_output.strip() else None
        if not ok:
            message = head_output.lower()
            if "not a git repository" in message or "fatal" in message:
                return (
                    "error: Cannot create worktree: the current directory "
                    f"'{current_cwd}' is not inside a git repository."
                )

        if worktree_path.exists():
            return (
                "error: Cannot create worktree: the path "
                f"'{worktree_path}' already exists. Provide a different 'path' "
                "argument or remove the existing directory."
            )

        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        ok, output = await _run_git(
            current_cwd,
            ["worktree", "add", "-b", branch, str(worktree_path)],
        )
        if not ok:
            lowered = output.lower()
            if "already exists" in lowered:
                return (
                    "error: Failed to create worktree: branch "
                    f"'{branch}' already exists. Use a different branch name or "
                    "delete the existing branch first."
                )
            if "not a git repository" in lowered:
                return (
                    "error: Failed to create worktree: "
                    f"'{current_cwd}' is not inside a git repository."
                )
            return f"error: Failed to create worktree: {output.strip()}"

        _WORKTREE_SESSIONS[session_key] = WorktreeSession(
            original_cwd=current_cwd,
            worktree_path=worktree_path,
            branch=branch,
            original_head=original_head,
        )
        ctx.session.cwd = str(worktree_path)

        post_create_command = str(input.get("post_create_command") or "").strip()
        post_create_output = ""
        if post_create_command:
            ok, output = await _run_shell(post_create_command, worktree_path)
            if ok:
                post_create_output = (
                    f"\nPost-create command '{post_create_command}' completed successfully."
                )
                if output:
                    post_create_output += f"\nOutput: {output}"
            else:
                post_create_output = (
                    f"\nPost-create command '{post_create_command}' exited with error.\n"
                    f"Stderr: {output}"
                )

        return (
            f"Created worktree at {worktree_path} on branch '{branch}'.\n"
            f"The working directory is now {worktree_path}.\n"
            f"Use ExitWorktree to return to {current_cwd}.{post_create_output}"
        )


class ExitWorktreeTool(Tool):
    name: ClassVar[str] = "ExitWorktree"
    permission_level = PermissionLevel.WRITE
    description: ClassVar[str] = (
        "Exit the current worktree session created by EnterWorktree and restore the "
        "original working directory. Use action='keep' to preserve the worktree on "
        "disk, or action='remove' to delete it. Only operates on worktrees created "
        "by EnterWorktree in this session."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["keep", "remove"],
                "description": "\"keep\" leaves the worktree on disk; \"remove\" deletes it and its branch.",
            },
            "discard_changes": {
                "type": "boolean",
                "description": (
                    "Set true when action=remove and the worktree has "
                    "uncommitted/unmerged work to discard."
                ),
            },
        },
        "required": ["action"],
    }

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        session_key = _session_key(ctx)
        session = _WORKTREE_SESSIONS.get(session_key)
        if session is None:
            return (
                "No-op: there is no active EnterWorktree session to exit. "
                "This tool only operates on worktrees created by EnterWorktree "
                "in the current session."
            )

        action = str(input.get("action") or "keep").strip().lower() or "keep"
        discard_changes = bool(input.get("discard_changes"))
        worktree_str = str(session.worktree_path)

        if action == "remove" and not discard_changes:
            ok, status_output = await _run_git(
                session.worktree_path,
                ["status", "--porcelain"],
            )
            changed_files = 0
            if ok:
                changed_files = len(
                    [line for line in status_output.splitlines() if line.strip()]
                )

            commit_count = 0
            if session.original_head:
                ok, rev_output = await _run_git(
                    session.worktree_path,
                    ["rev-list", "--count", f"{session.original_head}..HEAD"],
                )
                if ok:
                    try:
                        commit_count = int(rev_output.strip() or "0")
                    except ValueError:
                        commit_count = 0

            if changed_files > 0 or commit_count > 0:
                parts: list[str] = []
                if changed_files > 0:
                    parts.append(f"{changed_files} uncommitted file(s)")
                if commit_count > 0:
                    parts.append(f"{commit_count} commit(s) on the worktree branch")
                return (
                    f"error: Worktree has {' and '.join(parts)}. Removing will discard "
                    "this work permanently. Confirm with the user, then re-invoke with "
                    "discard_changes=true — or use action=\"keep\" to preserve the worktree."
                )

        if action == "keep":
            await _run_git(
                session.original_cwd,
                ["worktree", "lock", "--reason", "kept by ExitWorktree", worktree_str],
            )
            ctx.session.cwd = str(session.original_cwd)
            _WORKTREE_SESSIONS.pop(session_key, None)
            return (
                f"Exited worktree. Work preserved at {session.worktree_path} on branch "
                f"{session.branch or '(unknown)'}. Session is now back in "
                f"{session.original_cwd}."
            )

        if action == "remove":
            await _run_git(
                session.original_cwd,
                ["worktree", "remove", "--force", worktree_str],
            )
            if session.branch:
                await _run_git(
                    session.original_cwd,
                    ["branch", "-D", session.branch],
                )
            ctx.session.cwd = str(session.original_cwd)
            _WORKTREE_SESSIONS.pop(session_key, None)
            return (
                f"Exited and removed worktree at {session.worktree_path}. "
                f"Session is now back in {session.original_cwd}."
            )

        return f"error: Unknown action '{action}'. Use 'keep' or 'remove'."
