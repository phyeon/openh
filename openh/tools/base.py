"""Tool ABC + permission types + execution context."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Awaitable, Callable, ClassVar, Literal

if TYPE_CHECKING:
    from ..session import AgentSession


class PermissionLevel(str, Enum):
    NONE = "none"
    READ_ONLY = "read_only"
    WRITE = "write"
    EXECUTE = "execute"
    DANGEROUS = "dangerous"
    FORBIDDEN = "forbidden"


@dataclass
class PermissionDecision:
    behavior: Literal["allow", "ask", "deny"]
    reason: str = ""
    updated_input: dict[str, Any] | None = None


@dataclass
class ToolContext:
    session: "AgentSession"
    request_permission: Callable[[str, dict[str, Any]], Awaitable[bool]]


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[dict[str, Any]]
    is_read_only: ClassVar[bool] = False
    is_destructive: ClassVar[bool] = False
    permission_level: ClassVar[PermissionLevel | None] = None

    def get_permission_level(self) -> PermissionLevel:
        if self.permission_level is not None:
            return self.permission_level
        if self.is_read_only:
            return PermissionLevel.READ_ONLY
        if self.is_destructive:
            return PermissionLevel.EXECUTE
        return PermissionLevel.WRITE

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        level = self.get_permission_level()
        if level in (PermissionLevel.NONE, PermissionLevel.READ_ONLY):
            return PermissionDecision(behavior="allow")
        return PermissionDecision(behavior="ask")

    @abstractmethod
    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        ...

    def to_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }
