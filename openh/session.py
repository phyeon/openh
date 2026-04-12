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
    total_cache_creation_input_tokens: int = 0
    total_cache_read_input_tokens: int = 0
    subagent_total_input_tokens: int = 0
    subagent_total_output_tokens: int = 0
    subagent_total_cache_creation_input_tokens: int = 0
    subagent_total_cache_read_input_tokens: int = 0
    last_input_tokens: int = 0      # context size of last API call
    total_estimated_cost_usd: float = 0.0
    subagent_total_estimated_cost_usd: float = 0.0
    usage_by_model: dict[str, dict[str, int | float]] = field(default_factory=dict)
    session_id: str = ""
    title: str = ""
    created_at: float = 0.0
    prompt_preset: str = ""       # per-session preset name (empty = global)
    prompt_override: str = ""     # per-session custom prompt text (empty = use preset)
    profile_id: str = "default"   # session profile ("default", "fnd", ...)
    shell_env: dict[str, str] = field(default_factory=dict)  # persisted env vars (CC pattern)
    managed_agent_enabled: bool = False
    managed_executor_model: str = ""
    managed_executor_max_turns: int = 10
    managed_max_concurrent_executors: int = 1
    managed_executor_isolation: bool = True
    session_memory_last_extracted_message_count: int = 0
    session_memory_last_extracted_tool_call_count: int = 0
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

    def add_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
        *,
        model: str | None = None,
        source: str = "direct",
        update_last_input: bool = True,
        propagate: bool = True,
    ) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cache_creation_input_tokens += cache_creation_input_tokens
        self.total_cache_read_input_tokens += cache_read_input_tokens
        context_input = (
            input_tokens
            + cache_creation_input_tokens
            + cache_read_input_tokens
        )
        if update_last_input and context_input > 0:
            self.last_input_tokens = context_input
        model_name = (model or getattr(self.provider, "model", "") or "").strip() or "unknown"
        cost_delta = estimate_cost_usd(
            model_name,
            input_tokens,
            output_tokens,
            cache_creation_input_tokens,
            cache_read_input_tokens,
        )
        self.total_estimated_cost_usd += cost_delta
        record_usage_by_model(
            self.usage_by_model,
            model_name,
            input_tokens,
            output_tokens,
            cache_creation_input_tokens,
            cache_read_input_tokens,
            cost_usd=cost_delta,
        )
        if source == "subagent":
            self.subagent_total_input_tokens += input_tokens
            self.subagent_total_output_tokens += output_tokens
            self.subagent_total_cache_creation_input_tokens += cache_creation_input_tokens
            self.subagent_total_cache_read_input_tokens += cache_read_input_tokens
            self.subagent_total_estimated_cost_usd += cost_delta

        if source == "direct" and propagate:
            parent = getattr(self, "_usage_parent", None)
            if isinstance(parent, AgentSession) and parent is not self:
                parent.add_tokens(
                    input_tokens,
                    output_tokens,
                    cache_creation_input_tokens,
                    cache_read_input_tokens,
                    model=model_name,
                    source="subagent",
                    update_last_input=False,
                    propagate=False,
                )


def normalize_usage_by_model(
    raw: object,
) -> dict[str, dict[str, int | float]]:
    normalized: dict[str, dict[str, int | float]] = {}
    if not isinstance(raw, dict):
        return normalized

    for model_name, entry in raw.items():
        if not isinstance(model_name, str) or not isinstance(entry, dict):
            continue
        normalized[model_name] = {
            "input_tokens": int(entry.get("input_tokens", 0) or 0),
            "output_tokens": int(entry.get("output_tokens", 0) or 0),
            "cache_creation_input_tokens": int(
                entry.get("cache_creation_input_tokens", 0) or 0
            ),
            "cache_read_input_tokens": int(
                entry.get("cache_read_input_tokens", 0) or 0
            ),
            "cost_usd": float(entry.get("cost_usd", 0.0) or 0.0),
            "requests": int(entry.get("requests", 0) or 0),
        }
    return normalized


def record_usage_by_model(
    usage_by_model: dict[str, dict[str, int | float]],
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    *,
    cost_usd: float = 0.0,
) -> None:
    model_name = (model or "").strip() or "unknown"
    entry = usage_by_model.setdefault(
        model_name,
        {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cost_usd": 0.0,
            "requests": 0,
        },
    )
    entry["input_tokens"] = int(entry.get("input_tokens", 0) or 0) + input_tokens
    entry["output_tokens"] = int(entry.get("output_tokens", 0) or 0) + output_tokens
    entry["cache_creation_input_tokens"] = int(
        entry.get("cache_creation_input_tokens", 0) or 0
    ) + cache_creation_input_tokens
    entry["cache_read_input_tokens"] = int(
        entry.get("cache_read_input_tokens", 0) or 0
    ) + cache_read_input_tokens
    entry["cost_usd"] = float(entry.get("cost_usd", 0.0) or 0.0) + cost_usd
    if (
        input_tokens
        or output_tokens
        or cache_creation_input_tokens
        or cache_read_input_tokens
        or cost_usd
    ):
        entry["requests"] = int(entry.get("requests", 0) or 0) + 1
