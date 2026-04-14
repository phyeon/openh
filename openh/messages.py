"""Internal message format (Anthropic-compatible) and stream events."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Union
import uuid as uuid_lib


# ---------- Content blocks ----------

@dataclass
class TextBlock:
    text: str
    type: Literal["text"] = "text"

    def to_dict(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text}


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: Literal["tool_use"] = "tool_use"
    _raw_part: Any = field(default=None, repr=False)  # preserve provider-specific Part (e.g. Gemini thought_signature)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}
        if self._raw_part is not None:
            try:
                d["_raw_part_json"] = self._raw_part.to_json_dict()
            except Exception:
                pass
        return d


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": self.content,
        }
        if self.is_error:
            d["is_error"] = True
        return d


@dataclass
class ImageBlock:
    data_base64: str         # base64-encoded image bytes
    media_type: str          # "image/png", "image/jpeg", etc.
    type: Literal["image"] = "image"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": self.media_type,
                "data": self.data_base64,
            },
        }


@dataclass
class DocumentBlock:
    data_base64: str         # base64-encoded PDF bytes
    media_type: str = "application/pdf"
    type: Literal["document"] = "document"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": self.media_type,
                "data": self.data_base64,
            },
        }


Block = Union[TextBlock, ToolUseBlock, ToolResultBlock, ImageBlock, DocumentBlock]


def new_message_uuid() -> str:
    return str(uuid_lib.uuid4())


@dataclass
class Message:
    role: Literal["user", "assistant"]
    content: list[Block]
    uuid: str | None = field(default_factory=new_message_uuid)

    def to_anthropic_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": [b.to_dict() for b in self.content],
        }


def text_message(role: Literal["user", "assistant"], text: str) -> Message:
    return Message(role=role, content=[TextBlock(text=text)])


# ---------- Stream events (provider-agnostic) ----------

@dataclass
class TextDelta:
    text: str


@dataclass
class ToolUseStart:
    id: str
    name: str


@dataclass
class ToolUseDelta:
    id: str
    partial_json: str


@dataclass
class ToolUseEnd:
    id: str
    name: str
    input: dict[str, Any]
    _raw_part: Any = field(default=None, repr=False)


@dataclass
class ToolResultEvent:
    tool_use_id: str
    tool_name: str
    content: str
    is_error: bool = False


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class MessageStop:
    stop_reason: str  # "end_turn", "tool_use", "max_tokens", etc.


@dataclass
class StatusEvent:
    text: str


StreamEvent = Union[
    TextDelta,
    ToolUseStart,
    ToolUseDelta,
    ToolUseEnd,
    ToolResultEvent,
    Usage,
    MessageStop,
    StatusEvent,
]
