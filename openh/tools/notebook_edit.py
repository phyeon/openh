"""NotebookEdit tool — edit Jupyter notebook (.ipynb) cells."""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, ClassVar

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext


class NotebookEditTool(Tool):
    name: ClassVar[str] = "NotebookEdit"
    permission_level = PermissionLevel.WRITE
    description: ClassVar[str] = (
        "Completely replaces the contents of a specific cell in a Jupyter notebook (.ipynb file). "
        "The notebook_path must be absolute. The cell_number is 0-indexed. "
        "Use edit_mode=insert to add a new cell at the index. "
        "Use edit_mode=delete to delete the cell at the index."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "notebook_path": {
                "type": "string",
                "description": "Absolute path to the .ipynb file.",
            },
            "cell_number": {
                "type": "integer",
                "description": "0-indexed cell number (for replace/delete, or insertion index for insert).",
            },
            "cell_id": {
                "type": "string",
                "description": "Optional cell ID. If provided, takes precedence over cell_number.",
            },
            "new_source": {
                "type": "string",
                "description": "Full new source for the cell (replace/insert).",
            },
            "cell_type": {
                "type": "string",
                "enum": ["code", "markdown"],
                "description": "Cell type. Required for insert. Defaults to current type for replace.",
            },
            "edit_mode": {
                "type": "string",
                "enum": ["replace", "insert", "delete"],
                "description": "Edit mode. Defaults to replace.",
            },
        },
        "required": ["notebook_path", "new_source"],
    }
    is_destructive: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        path_str = input.get("notebook_path")
        if not path_str:
            return "error: notebook_path is required"
        path = Path(path_str)
        if not path.is_absolute():
            return f"error: notebook_path must be absolute, got: {path_str}"
        if not path.exists():
            return f"error: notebook does not exist: {path_str}"
        if path.suffix != ".ipynb":
            return f"error: not a .ipynb file: {path_str}"

        # Read-before-write enforcement
        resolved = str(path.resolve())
        if resolved not in ctx.session.read_files:
            return (
                f"error: notebook {path_str} must be Read in this session before editing."
            )

        try:
            nb = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return f"error: invalid notebook JSON: {exc}"

        cells = nb.get("cells")
        if not isinstance(cells, list):
            return "error: notebook has no cells list"

        edit_mode = input.get("edit_mode") or "replace"
        cell_id = input.get("cell_id")
        cell_number = input.get("cell_number")
        new_source = input.get("new_source") or ""
        cell_type = input.get("cell_type")

        # Resolve target index
        idx: int | None = None
        if cell_id:
            for i, c in enumerate(cells):
                if c.get("id") == cell_id:
                    idx = i
                    break
            if idx is None and edit_mode != "insert":
                return f"error: no cell with id={cell_id}"
        elif cell_number is not None:
            try:
                idx = int(cell_number)
            except (TypeError, ValueError):
                return "error: cell_number must be an integer"
        elif edit_mode != "insert":
            return "error: cell_number or cell_id required for replace/delete"

        if edit_mode == "replace":
            if idx is None or idx < 0 or idx >= len(cells):
                return f"error: cell_number {cell_number} out of range (0..{len(cells)-1})"
            target = cells[idx]
            target["source"] = _split_source(new_source)
            if cell_type:
                target["cell_type"] = cell_type
            # Clear outputs if it's a code cell
            if target.get("cell_type") == "code":
                target["outputs"] = []
                target["execution_count"] = None
            msg = f"replaced cell {idx}"
        elif edit_mode == "insert":
            if not cell_type:
                return "error: cell_type is required for insert"
            new_cell: dict[str, Any] = {
                "cell_type": cell_type,
                "id": uuid.uuid4().hex[:8],
                "metadata": {},
                "source": _split_source(new_source),
            }
            if cell_type == "code":
                new_cell["outputs"] = []
                new_cell["execution_count"] = None
            # If cell_id was provided, insert *after* that cell (Claude Code semantics)
            if cell_id:
                # idx already found
                if idx is None:
                    cells.insert(0, new_cell)
                    msg = f"inserted new {cell_type} cell at position 0"
                else:
                    cells.insert(idx + 1, new_cell)
                    msg = f"inserted new {cell_type} cell at position {idx + 1}"
            else:
                insert_at = idx if idx is not None else len(cells)
                cells.insert(insert_at, new_cell)
                msg = f"inserted new {cell_type} cell at position {insert_at}"
        elif edit_mode == "delete":
            if idx is None or idx < 0 or idx >= len(cells):
                return f"error: cell_number {cell_number} out of range"
            removed = cells.pop(idx)
            msg = f"deleted cell {idx} ({removed.get('cell_type', '?')})"
        else:
            return f"error: unknown edit_mode: {edit_mode}"

        try:
            path.write_text(
                json.dumps(nb, indent=1, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            return f"error: write failed: {exc}"

        ctx.session.read_files.add(resolved)
        return f"{msg} in {path}"


def _split_source(text: str) -> list[str]:
    """Jupyter stores source as a list of lines (each ending in \\n except last)."""
    if not text:
        return []
    lines = text.splitlines(keepends=True)
    return lines
