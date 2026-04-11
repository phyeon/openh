"""Per-session mutable state: history, provider, tokens."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .config import Config
from .messages import Block, Message, TextBlock, ToolResultBlock

if TYPE_CHECKING:
    from .providers.base import Provider
    from .tools.base import Tool


@dataclass
class AgentSession:
    config: Config
    provider: "Provider"
    messages: list[Message] = field(default_factory=list)
    tools: list["Tool"] = field(default_factory=list)
    read_files: set[str] = field(default_factory=set)
    always_allow: set[tuple[str, str]] = field(default_factory=set)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    last_input_tokens: int = 0      # context size of last API call
    session_id: str = ""
    title: str = ""
    created_at: float = 0.0
    prompt_preset: str = ""       # per-session preset name (empty = global)
    prompt_override: str = ""     # per-session custom prompt text (empty = use preset)
    _cwd: str = ""

    @property
    def cwd(self) -> str:
        return self._cwd or self.config.cwd

    @cwd.setter
    def cwd(self, value: str) -> None:
        self._cwd = value

    def switch_provider(self, provider: "Provider") -> None:
        self.provider = provider

    def append_user_text(self, text: str) -> None:
        self.messages.append(Message(role="user", content=[TextBlock(text=text)]))

    def append_assistant_message(self, blocks: list[Block]) -> None:
        if not blocks:
            return
        self.messages.append(Message(role="assistant", content=list(blocks)))

    def append_tool_results(self, results: list[ToolResultBlock]) -> None:
        if not results:
            return
        self.messages.append(Message(role="user", content=list(results)))

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        if input_tokens > 0:
            self.last_input_tokens = input_tokens
