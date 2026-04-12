"""EnterWorktree / ExitWorktree — git worktree isolation tools."""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext


class EnterWorktreeTool(Tool):
    name = "EnterWorktree"
    permission_level = PermissionLevel.WRITE
    description = (
        "Create an isolated git worktree so the agent works on a separate "
        "copy of the repo. Useful for parallel work or risky experiments."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Optional name for the worktree branch.",
            },
        },
    }
    is_read_only = False

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        cwd = os.getcwd()
        # Check we are in a git repo
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--git-dir",
            cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return "Error: not inside a git repository."

        branch_name = input.get("name") or f"openh-wt-{uuid.uuid4().hex[:8]}"
        wt_dir = Path(cwd) / ".openh" / "worktrees" / branch_name
        wt_dir.parent.mkdir(parents=True, exist_ok=True)

        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", "-b", branch_name, str(wt_dir),
            cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return f"Error creating worktree: {stderr.decode().strip()}"

        os.chdir(str(wt_dir))
        return f"Created worktree at {wt_dir} on branch '{branch_name}'. Working directory changed."


class ExitWorktreeTool(Tool):
    name = "ExitWorktree"
    permission_level = PermissionLevel.WRITE
    description = (
        "Exit the current worktree and optionally remove it."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["keep", "remove"],
                "description": "'keep' leaves the worktree on disk; 'remove' deletes it.",
            },
        },
        "required": ["action"],
    }
    is_read_only = False

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        cwd = os.getcwd()
        action = input.get("action", "keep")

        # Detect worktree root
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--show-toplevel",
            cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        wt_root = stdout.decode().strip()

        # Go back to main worktree
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "list", "--porcelain",
            cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        lines = stdout.decode().splitlines()
        main_dir = None
        for line in lines:
            if line.startswith("worktree "):
                candidate = line.split(" ", 1)[1]
                if candidate != wt_root:
                    main_dir = candidate
                    break

        if main_dir:
            os.chdir(main_dir)

        if action == "remove":
            proc = await asyncio.create_subprocess_exec(
                "git", "worktree", "remove", "--force", wt_root,
                cwd=main_dir or cwd,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return f"Removed worktree at {wt_root}. Returned to {main_dir or cwd}."
        return f"Left worktree at {wt_root} (kept on disk). Returned to {main_dir or cwd}."
