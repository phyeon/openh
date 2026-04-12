"""TodoWrite tool — maintain a structured todo list for the current session."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, ClassVar

from ..cc_compat import TODOS_DIR
from .base import PermissionDecision, Tool, ToolContext

_VALID_STATUSES = {"pending", "in_progress", "completed"}


def _todo_path(session_id: str) -> Path:
    return TODOS_DIR / f"{session_id}.json"


def _load_persisted_todos(session_id: str) -> list[dict[str, Any]]:
    if not session_id:
        return []
    path = _todo_path(session_id)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _save_todos(session_id: str, todos: list[dict[str, Any]]) -> None:
    if not session_id:
        return
    TODOS_DIR.mkdir(parents=True, exist_ok=True)
    _todo_path(session_id).write_text(
        json.dumps(todos, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _normalize_status(raw: Any) -> str | None:
    status = str(raw or "").strip().lower()
    return status if status in _VALID_STATUSES else None


def _make_todo_id(content: str, index: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", content.lower()).strip("-")
    return slug or f"todo-{index}"


def _validate_transition(todo_id: str, old: str, new: str) -> str | None:
    if old == new:
        return None
    if old == "completed":
        return (
            f"error: task '{todo_id}' cannot change status after completion "
            f"(completed -> {new})"
        )
    if old == "in_progress" and new == "pending":
        return f"error: task '{todo_id}' cannot move backwards (in_progress -> pending)"
    return None


class TodoWriteTool(Tool):
    name: ClassVar[str] = "TodoWrite"
    description: ClassVar[str] = (
        "Write and manage a structured todo list for the current session. "
        "Provide the complete list of todos each time; this replaces the prior list. "
        "Use stable ids when possible. Task states: pending, in_progress, completed. "
        "Only have one task in_progress at a time, and do not reopen completed tasks."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Full list of todo items (replaces the previous list).",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Stable task id. Recommended for updates across calls.",
                        },
                        "content": {
                            "type": "string",
                            "description": "Imperative form (e.g. 'Run tests').",
                        },
                        "activeForm": {
                            "type": "string",
                            "description": "Present continuous (e.g. 'Running tests').",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                        "priority": {
                            "type": "string",
                            "description": "Optional priority label.",
                        },
                    },
                    "required": ["content", "status"],
                },
            },
        },
        "required": ["todos"],
    }
    is_read_only: ClassVar[bool] = False
    is_destructive: ClassVar[bool] = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        todos = input.get("todos") or []
        if not isinstance(todos, list):
            return "error: todos must be a list"

        persisted = _load_persisted_todos(ctx.session.session_id)
        previous_status = {
            str(item.get("id", "")): str(item.get("status", ""))
            for item in persisted
            if item.get("id")
        }

        normalized: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for index, raw in enumerate(todos, start=1):
            if not isinstance(raw, dict):
                return "error: each todo must be an object"

            content = str(raw.get("content") or "").strip()
            if not content:
                return f"error: todo #{index} is missing content"

            status = _normalize_status(raw.get("status"))
            if status is None:
                return (
                    f"error: todo '{content}' has invalid status "
                    "(must be pending, in_progress, or completed)"
                )

            todo_id = str(raw.get("id") or _make_todo_id(content, index)).strip()
            if not todo_id:
                return f"error: todo '{content}' is missing id"
            if todo_id in seen_ids:
                return f"error: duplicate todo id '{todo_id}'"
            seen_ids.add(todo_id)

            prior = previous_status.get(todo_id)
            if prior:
                transition_error = _validate_transition(todo_id, prior, status)
                if transition_error is not None:
                    return transition_error

            item = {
                "id": todo_id,
                "content": content,
                "status": status,
            }
            active_form = str(raw.get("activeForm") or "").strip()
            if active_form:
                item["activeForm"] = active_form
            priority = str(raw.get("priority") or "").strip()
            if priority:
                item["priority"] = priority
            normalized.append(item)

        # Store on the session so the UI can read it
        if not hasattr(ctx.session, "todos"):
            setattr(ctx.session, "todos", [])
        ctx.session.todos = normalized  # type: ignore[attr-defined]
        _save_todos(ctx.session.session_id, normalized)

        # Validate that at most one is in_progress
        in_progress = [t for t in normalized if t.get("status") == "in_progress"]
        warn = ""
        if len(in_progress) > 1:
            warn = f" (warning: {len(in_progress)} items marked in_progress; should be 1)"

        lines = [f"Todo list updated ({len(normalized)} items){warn}"]
        for t in normalized:
            status = t.get("status", "pending")
            mark = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}.get(status, "[ ]")
            lines.append(f"  {mark} {t.get('content', '')}")
        return "\n".join(lines)
