"""Per-session mutable state: history, provider, tokens."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .config import Config
from .messages import Block, Message, TextBlock, ToolResultBlock
from .pricing import estimate_cost_usd

if TYPE_CHECKING:
    from .providers.base import Provider
    from .tools.base import Tool


@dataclass
class AgentSession:
    config: Config
    provider: "Provider"
    messages: list[Message] = field(default_factory=list)
    model_messages: list[Message] = field(default_factory=list)
    tools: list["Tool"] = field(default_factory=list)
    read_files: set[str] = field(default_factory=set)
    always_allow: set[tuple[str, str]] = field(default_factory=set)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    last_input_tokens: int = 0      # context size of last API call
    total_estimated_cost_usd: float = 0.0
    session_id: str = ""
    title: str = ""
    created_at: float = 0.0
    prompt_preset: str = ""       # per-session preset name (empty = global)
    prompt_override: str = ""     # per-session custom prompt text (empty = use preset)
    profile_id: str = "default"   # session profile ("default", "fnd", ...)
    shell_env: dict[str, str] = field(default_factory=dict)  # persisted env vars (CC pattern)
    _cwd: str = ""

    @property
    def cwd(self) -> str:
        return self._cwd or self.config.cwd

    @cwd.setter
    def cwd(self, value: str) -> None:
        self._cwd = value

    def switch_provider(self, provider: "Provider") -> None:
        self.provider = provider

    def __post_init__(self) -> None:
        if not self.model_messages:
            self.reset_model_messages()

    def _copy_message(self, message: Message) -> Message:
        return Message(role=message.role, content=list(message.content))

    def _is_compaction_marker(self, message: Message) -> bool:
        if len(message.content) != 1:
            return False
        block = message.content[0]
        if not isinstance(block, TextBlock):
            return False
        text = block.text.strip()
        if text.startswith("[Conversation compacted"):
            return True
        if message.role == "assistant" and text == "Understood. Continuing from the recent context.":
            return True
        return False

    def reset_model_messages(self) -> None:
        self.model_messages = [
            self._copy_message(message)
            for message in self.messages
            if not self._is_compaction_marker(message)
        ]

    def append_message(
        self,
        role: str,
        blocks: list[Block],
        *,
        include_in_transcript: bool = True,
        include_in_model: bool = True,
    ) -> None:
        if not blocks:
            return
        message = Message(role=role, content=list(blocks))
        if include_in_transcript:
            self.messages.append(message)
        if include_in_model:
            self.model_messages.append(self._copy_message(message))

    def append_user_text(self, text: str) -> None:
        self.append_message("user", [TextBlock(text=text)])

    def append_assistant_message(self, blocks: list[Block]) -> None:
        self.append_message("assistant", blocks)

    def append_tool_results(self, results: list[ToolResultBlock]) -> None:
        self.append_message("user", list(results))

    def add_tokens(self, input_tokens: int, output_tokens: int) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        if input_tokens > 0:
            self.last_input_tokens = input_tokens
        self.total_estimated_cost_usd += estimate_cost_usd(
            getattr(self.provider, "model", ""),
            input_tokens,
            output_tokens,
        )
