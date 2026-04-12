"""ToolSearch — search available tools by keyword or direct selection."""
from __future__ import annotations

from typing import Any

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext

_TOOL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Agent": ("agent", "subagent", "delegate", "parallel", "worker", "background", "worktree"),
    "AskUserQuestion": ("ask", "question", "clarify", "user", "input"),
    "Bash": ("shell", "terminal", "command", "run", "exec", "background"),
    "BashOutput": ("shell", "background", "output", "logs"),
    "Edit": ("edit", "modify", "replace", "patch", "file"),
    "EnterPlanMode": ("plan", "planning", "analysis", "mode"),
    "ExitPlanMode": ("plan", "planning", "exit", "mode"),
    "EnterWorktree": ("worktree", "git", "isolate", "branch"),
    "ExitWorktree": ("worktree", "git", "remove", "restore"),
    "Glob": ("glob", "pattern", "files", "find", "path", "filename"),
    "Grep": ("grep", "regex", "search", "content", "pattern", "match"),
    "KillShell": ("shell", "background", "stop", "kill"),
    "MemoryDelete": ("memory", "delete", "remove"),
    "MemoryList": ("memory", "list", "recall"),
    "MemorySave": ("memory", "save", "note", "remember"),
    "monitor": ("monitor", "background", "task", "status", "output", "cancel"),
    "NotebookEdit": ("notebook", "jupyter", "ipynb", "cell"),
    "Read": ("read", "file", "content", "lines", "pdf", "image"),
    "SendMessage": ("message", "agent", "status", "follow-up", "resume"),
    "Skill": ("skill", "template", "prompt", "command", "workflow"),
    "TaskCreate": ("task", "create", "track", "board", "delegate", "work"),
    "TaskGet": ("task", "get", "status", "details"),
    "TaskUpdate": ("task", "update", "status", "progress"),
    "TaskList": ("task", "list", "all", "tasks"),
    "TaskOutput": ("task", "output", "result", "status"),
    "TaskStop": ("task", "cancel", "stop", "finish"),
    "TodoWrite": ("todo", "task", "plan", "checklist", "progress"),
    "ToolSearch": ("tool", "search", "discover", "select", "keyword"),
    "WebFetch": ("web", "fetch", "http", "url", "page"),
    "WebSearch": ("web", "search", "internet", "lookup"),
    "Write": ("write", "create", "save", "file"),
}


class ToolSearchTool(Tool):
    name = "ToolSearch"
    permission_level = PermissionLevel.NONE
    description = (
        "Search for available tools by name or keyword. "
        "Use 'select:ToolName' for direct lookup or provide keywords for fuzzy search. "
        "Returns matching tool names and descriptions."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Query string. Use 'select:ToolName' for direct selection, or keywords for fuzzy search.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return. Defaults to 5.",
            },
        },
        "required": ["query"],
    }
    is_read_only = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        query = str(input.get("query", "")).strip()
        if not query:
            return "error: query is required"

        max_results = max(1, min(int(input.get("max_results") or 5), 20))
        catalog = []
        for tool in ctx.session.tools:
            schema = getattr(tool, "input_schema", {}) or {}
            prop_names = tuple(str(key) for key in (schema.get("properties") or {}).keys())
            catalog.append(
                (
                    getattr(tool, "name", ""),
                    getattr(tool, "description", ""),
                    _TOOL_KEYWORDS.get(getattr(tool, "name", ""), ()),
                    prop_names,
                )
            )

        if query.lower().startswith("select:"):
            wanted = [part.strip() for part in query.split(":", 1)[1].split(",") if part.strip()]
            found: list[str] = []
            missing: list[str] = []
            for item in wanted:
                match = next((row for row in catalog if row[0].lower() == item.lower()), None)
                if match is None:
                    missing.append(item)
                else:
                    found.append(f"{match[0]}: {match[1]}")
            if not found:
                return f"No matching tools found for: {', '.join(missing)}"
            out = "\n".join(found)
            if missing:
                out += f"\n\nNot found: {', '.join(missing)}"
            return out

        terms = query.lower().split()
        scored: list[tuple[int, str, str]] = []
        for name, desc, keywords, schema_props in catalog:
            name_l = name.lower()
            desc_l = desc.lower()
            score = 0
            for term in terms:
                if name_l == term:
                    score += 20
                elif term in name_l:
                    score += 10
                if term in desc_l:
                    score += 5
                for keyword in keywords:
                    keyword_l = keyword.lower()
                    if keyword_l == term:
                        score += 8
                    elif term in keyword_l:
                        score += 3
                for prop in schema_props:
                    prop_l = prop.lower()
                    if prop_l == term:
                        score += 4
                    elif term in prop_l:
                        score += 2
            if score > 0:
                scored.append((score, name, desc))

        scored.sort(key=lambda row: (-row[0], row[1]))
        scored = scored[:max_results]
        if not scored:
            return f"No tools found matching '{query}'. Try broader keywords or use 'select:ToolName'."

        lines = [f"{name}: {desc}" for _, name, desc in scored]
        return (
            f"Tools matching '{query}':\n\n"
            + "\n".join(lines)
            + f"\n\nTotal tools available: {len(catalog)}"
        )
