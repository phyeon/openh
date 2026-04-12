"""Tool registry."""
from __future__ import annotations

from .agent_tool import AgentTool
from .ask_user import AskUserQuestionTool
from .base import PermissionDecision, Tool, ToolContext
from .bash import BashOutputTool, BashTool, KillShellTool
from .edit import EditTool
from .glob import GlobTool
from .grep import GrepTool
from .ls import LSTool
from .memory_tools import MemoryDeleteTool, MemoryListTool, MemorySaveTool
from .notebook_edit import NotebookEditTool
from .planmode import EnterPlanModeTool, ExitPlanModeTool
from .read import ReadTool
from .send_message import SendMessageTool
from .skill_tool import SkillTool
from .task_tools import (
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskOutputTool,
    TaskStopTool,
    TaskUpdateTool,
)
from .todowrite import TodoWriteTool
from .tool_search import ToolSearchTool
from .webfetch import WebFetchTool
from .websearch import WebSearchTool
from .worktree import EnterWorktreeTool, ExitWorktreeTool
from .serial_tool import SerialTool
from .write import WriteTool

__all__ = [
    "Tool",
    "PermissionDecision",
    "ToolContext",
    "default_tools",
    "ReadTool",
    "WriteTool",
    "EditTool",
    "BashTool",
    "BashOutputTool",
    "KillShellTool",
    "GlobTool",
    "GrepTool",
    "LSTool",
    "TodoWriteTool",
    "WebFetchTool",
    "WebSearchTool",
    "AgentTool",
    "EnterPlanModeTool",
    "ExitPlanModeTool",
    "NotebookEditTool",
    "SkillTool",
    "MemorySaveTool",
    "MemoryListTool",
    "MemoryDeleteTool",
    "AskUserQuestionTool",
    "EnterWorktreeTool",
    "ExitWorktreeTool",
    "TaskCreateTool",
    "TaskGetTool",
    "TaskUpdateTool",
    "TaskListTool",
    "TaskOutputTool",
    "TaskStopTool",
    "SendMessageTool",
    "ToolSearchTool",
    "SerialTool",
    "fnd_extra_tools",
]


def fnd_extra_tools() -> list[Tool]:
    """Extra tools for FnD (Fruits & Dessert) profile sessions only."""
    return [SerialTool()]


def default_tools() -> list[Tool]:
    return [
        ReadTool(),
        LSTool(),
        GlobTool(),
        GrepTool(),
        EditTool(),
        WriteTool(),
        BashTool(),
        BashOutputTool(),
        KillShellTool(),
        NotebookEditTool(),
        TodoWriteTool(),
        WebFetchTool(),
        WebSearchTool(),
        AgentTool(),
        EnterPlanModeTool(),
        ExitPlanModeTool(),
        SkillTool(),
        MemorySaveTool(),
        MemoryListTool(),
        MemoryDeleteTool(),
        AskUserQuestionTool(),
        EnterWorktreeTool(),
        ExitWorktreeTool(),
        TaskCreateTool(),
        TaskGetTool(),
        TaskUpdateTool(),
        TaskListTool(),
        TaskStopTool(),
        TaskOutputTool(),
        SendMessageTool(),
        ToolSearchTool(),
    ]
