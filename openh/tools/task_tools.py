"""Task board tools — TaskCreate, TaskGet, TaskUpdate, TaskList, TaskStop, TaskOutput."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

from .agent_tool import get_coordination_root
from .base import PermissionDecision, Tool, ToolContext

_VALID_STATUSES = {
    "pending",
    "in_progress",
    "completed",
    "deleted",
    "running",
    "failed",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRecord:
    id: str
    subject: str
    description: str
    status: str = "pending"
    owner: str | None = None
    blocks: list[str] = field(default_factory=list)
    blocked_by: list[str] = field(default_factory=list)
    metadata: dict[str, Any] | list[Any] | str | int | float | bool | None = None
    output: str | None = None
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "status": self.status,
            "owner": self.owner,
            "blocked_by": list(self.blocked_by),
        }

    def to_full(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "description": self.description,
            "status": self.status,
            "owner": self.owner,
            "blocks": list(self.blocks),
            "blocked_by": list(self.blocked_by),
            "metadata": self.metadata,
            "output": self.output,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _task_store(session) -> dict[str, TaskRecord]:
    root = get_coordination_root(session)
    store = getattr(root, "_task_store", None)
    if store is None:
        store = {}
        setattr(root, "_task_store", store)
    return store


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _task_id(input: dict[str, Any]) -> str:
    return str(
        input.get("task_id")
        or input.get("taskId")
        or input.get("shell_id")
        or ""
    ).strip()


def _normalize_status(value: str) -> str | None:
    status = str(value or "").strip().lower().replace("-", "_")
    if status in _VALID_STATUSES:
        return status
    return None


def _merge_unique(existing: list[str], new_items: Any) -> list[str]:
    merged = list(existing)
    if not isinstance(new_items, list):
        return merged
    for item in new_items:
        text = str(item or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged


class TaskCreateTool(Tool):
    name: ClassVar[str] = "TaskCreate"
    description: ClassVar[str] = (
        "Create a new task in the shared task board for delegated or multi-step work. "
        "Returns the new task ID."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Brief title for the task.",
            },
            "description": {
                "type": "string",
                "description": "Detailed description of the work item.",
            },
            "metadata": {
                "description": "Optional metadata payload for the task.",
            },
        },
        "required": ["subject", "description"],
    }
    is_read_only = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        subject = str(input.get("subject", "")).strip()
        description = str(input.get("description", "")).strip()
        if not subject:
            return "Error: subject is required."
        if not description:
            return "Error: description is required."

        task = TaskRecord(
            id=str(uuid.uuid4()),
            subject=subject,
            description=description,
            metadata=input.get("metadata"),
        )
        _task_store(ctx.session)[task.id] = task
        return _json({"task_id": task.id, "subject": task.subject})


class TaskGetTool(Tool):
    name: ClassVar[str] = "TaskGet"
    description: ClassVar[str] = "Get full details of a task by ID."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID to retrieve.",
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
        task_id = _task_id(input)
        task = _task_store(ctx.session).get(task_id)
        if task is None:
            return _json(None)
        return _json(task.to_full())


class TaskUpdateTool(Tool):
    name: ClassVar[str] = "TaskUpdate"
    description: ClassVar[str] = (
        "Update a task's properties such as status, owner, description, dependencies, or output."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task ID to update."},
            "subject": {"type": "string"},
            "description": {"type": "string"},
            "status": {
                "type": "string",
                "enum": sorted(_VALID_STATUSES - {"running"}),
            },
            "owner": {"type": "string"},
            "addBlocks": {"type": "array", "items": {"type": "string"}},
            "addBlockedBy": {"type": "array", "items": {"type": "string"}},
            "metadata": {"description": "Replacement metadata payload."},
            "output": {"type": "string"},
        },
        "required": ["task_id"],
    }
    is_read_only = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        task_id = _task_id(input)
        task = _task_store(ctx.session).get(task_id)
        if task is None:
            return f"Error: task '{task_id}' not found."

        updated_fields: list[str] = []
        subject = str(input.get("subject", "")).strip()
        if subject:
            task.subject = subject
            updated_fields.append("subject")

        description = str(input.get("description", "")).strip()
        if description:
            task.description = description
            updated_fields.append("description")

        if "status" in input:
            status = _normalize_status(str(input.get("status") or ""))
            if status is None:
                return f"Error: unknown status '{input.get('status')}'."
            task.status = status
            updated_fields.append("status")

        if "owner" in input:
            owner = str(input.get("owner") or "").strip()
            task.owner = owner or None
            updated_fields.append("owner")

        add_blocks = input.get("addBlocks")
        if add_blocks is not None:
            task.blocks = _merge_unique(task.blocks, add_blocks)
            updated_fields.append("blocks")

        add_blocked_by = input.get("addBlockedBy")
        if add_blocked_by is not None:
            task.blocked_by = _merge_unique(task.blocked_by, add_blocked_by)
            updated_fields.append("blocked_by")

        if "metadata" in input:
            task.metadata = input.get("metadata")
            updated_fields.append("metadata")

        if "output" in input:
            task.output = str(input.get("output") or "")
            updated_fields.append("output")

        task.updated_at = _now_iso()
        if task.status == "deleted":
            _task_store(ctx.session).pop(task_id, None)

        return _json(
            {
                "success": True,
                "task_id": task_id,
                "updated_fields": updated_fields,
            }
        )


class TaskListTool(Tool):
    name: ClassVar[str] = "TaskList"
    description: ClassVar[str] = "List active tasks in the shared task board."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "include_completed": {
                "type": "boolean",
                "description": "Include completed tasks. Defaults to false.",
            },
        },
    }
    is_read_only = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        include_completed = bool(input.get("include_completed", False))
        tasks = sorted(
            _task_store(ctx.session).values(),
            key=lambda item: item.created_at,
        )
        visible = [
            task.to_summary()
            for task in tasks
            if task.status != "deleted"
            and (include_completed or task.status != "completed")
        ]
        return _json(visible)


class TaskStopTool(Tool):
    name: ClassVar[str] = "TaskStop"
    description: ClassVar[str] = "Stop a running or in-progress task."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID to stop.",
            },
        },
        "required": ["task_id"],
    }
    is_read_only = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        task_id = _task_id(input)
        task = _task_store(ctx.session).get(task_id)
        if task is None:
            return f"Error: task '{task_id}' not found."
        if task.status not in {"running", "in_progress"}:
            return (
                f"Error: task '{task_id}' is not running "
                f"(status: {task.status})."
            )
        task.status = "completed"
        task.updated_at = _now_iso()
        return _json({"message": "Task stopped", "task_id": task_id})


class TaskOutputTool(Tool):
    name: ClassVar[str] = "TaskOutput"
    description: ClassVar[str] = "Get the current output of a task."
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "Task ID to fetch output for.",
            },
            "block": {
                "type": "boolean",
                "description": "Wait for completion before returning. Defaults to true.",
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
        task_id = _task_id(input)
        task = _task_store(ctx.session).get(task_id)
        if task is None:
            return f"Error: task '{task_id}' not found."

        block = bool(input.get("block", True))
        retrieval_status = "success"
        if task.status in {"running", "in_progress"} and not block:
            retrieval_status = "not_ready"

        return _json(
            {
                "retrieval_status": retrieval_status,
                "task": task.to_full(),
            }
        )
