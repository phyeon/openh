"""Background task management tools — TaskCreate, TaskOutput, TaskStop."""
from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any

from .base import PermissionDecision, Tool, ToolContext

# In-process task registry (session-scoped)
_TASKS: dict[str, dict[str, Any]] = {}


class TaskCreateTool(Tool):
    name = "TaskCreate"
    description = (
        "Launch a background shell command as a task. Returns a task_id "
        "that can be used with TaskOutput and TaskStop."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to run in the background.",
            },
        },
        "required": ["command"],
    }
    is_read_only = False

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        command = input.get("command", "")
        if not command:
            return "Error: command is required."
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=os.getcwd(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        _TASKS[task_id] = {
            "command": command,
            "process": proc,
            "output_chunks": [],
        }
        # Start collecting output in background
        asyncio.get_event_loop().create_task(_collect_output(task_id, proc))
        return f"Task started: {task_id}\nCommand: {command}"


async def _collect_output(task_id: str, proc: asyncio.subprocess.Process) -> None:
    entry = _TASKS.get(task_id)
    if not entry or not proc.stdout:
        return
    while True:
        chunk = await proc.stdout.read(4096)
        if not chunk:
            break
        entry["output_chunks"].append(chunk.decode(errors="replace"))
    await proc.wait()


class TaskOutputTool(Tool):
    name = "TaskOutput"
    description = "Get output from a running or completed background task."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The task ID from TaskCreate.",
            },
        },
        "required": ["task_id"],
    }
    is_read_only = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        task_id = input.get("task_id", "")
        entry = _TASKS.get(task_id)
        if not entry:
            return f"Error: unknown task_id '{task_id}'."
        proc: asyncio.subprocess.Process = entry["process"]
        status = "running" if proc.returncode is None else f"exited ({proc.returncode})"
        output = "".join(entry["output_chunks"])
        if len(output) > 8000:
            output = output[:4000] + "\n…truncated…\n" + output[-4000:]
        return f"Status: {status}\n\n{output}"


class TaskStopTool(Tool):
    name = "TaskStop"
    description = "Stop a running background task."
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "The task ID to stop.",
            },
        },
        "required": ["task_id"],
    }
    is_read_only = False

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        task_id = input.get("task_id", "")
        entry = _TASKS.get(task_id)
        if not entry:
            return f"Error: unknown task_id '{task_id}'."
        proc: asyncio.subprocess.Process = entry["process"]
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
        return f"Task {task_id} stopped."
