"""Tool ABC + permission types + execution context."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable, ClassVar, Literal

if TYPE_CHECKING:
    from ..session import AgentSession


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

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        if self.is_read_only:
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
