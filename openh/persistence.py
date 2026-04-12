"""Session persistence: save/load conversations to ~/.openh/sessions/*.json."""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .messages import Block, Message, TextBlock, ToolResultBlock, ToolUseBlock

SESSIONS_DIR = Path.home() / ".openh" / "sessions"


@dataclass
class SessionMeta:
    session_id: str
    title: str
    created_at: float
    updated_at: float
    path: Path

    def date_group(self, now: float | None = None) -> str:
        now = now or time.time()
        delta = now - self.updated_at
        if delta < 24 * 3600:
            return "Today"
        if delta < 48 * 3600:
            return "Yesterday"
        if delta < 7 * 24 * 3600:
            return "This week"
        return "Previous"


def ensure_dir() -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]


def _block_to_dict(block: Block) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    return {"type": "unknown"}


def _dict_to_block(d: dict[str, Any]) -> Block | None:
    t = d.get("type")
    if t == "text":
        return TextBlock(text=d.get("text", ""))
    if t == "tool_use":
        return ToolUseBlock(
            id=d.get("id", ""),
            name=d.get("name", ""),
            input=d.get("input", {}) or {},
        )
    if t == "tool_result":
        return ToolResultBlock(
            tool_use_id=d.get("tool_use_id", ""),
            content=d.get("content", ""),
            is_error=bool(d.get("is_error", False)),
        )
    return None


def message_to_dict(msg: Message) -> dict[str, Any]:
    return {
        "role": msg.role,
        "content": [_block_to_dict(b) for b in msg.content],
        "uuid": msg.uuid,
    }


def dict_to_message(d: dict[str, Any]) -> Message | None:
    role = d.get("role")
    if role not in ("user", "assistant"):
        return None
    blocks: list[Block] = []
    for bd in d.get("content", []) or []:
        b = _dict_to_block(bd)
        if b is not None:
            blocks.append(b)
    return Message(role=role, content=blocks, uuid=d.get("uuid"))


def save_session(
    session_id: str,
    title: str,
    messages: list[Message],
    in_tokens: int,
    out_tokens: int,
    model: str,
    provider_name: str,
    created_at: float | None = None,
) -> Path:
    ensure_dir()
    now = time.time()
    path = SESSIONS_DIR / f"{session_id}.json"
    data = {
        "session_id": session_id,
        "title": title,
        "created_at": created_at or now,
        "updated_at": now,
        "provider": provider_name,
        "model": model,
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "messages": [message_to_dict(m) for m in messages],
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_session(path: Path) -> tuple[dict[str, Any], list[Message]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    messages: list[Message] = []
    for md in data.get("messages", []) or []:
        m = dict_to_message(md)
        if m is not None:
            messages.append(m)
    return data, messages


def list_sessions() -> list[SessionMeta]:
    ensure_dir()
    metas: list[SessionMeta] = []
    for p in SESSIONS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        metas.append(
            SessionMeta(
                session_id=data.get("session_id", p.stem),
                title=data.get("title", "Untitled"),
                created_at=float(data.get("created_at", p.stat().st_mtime)),
                updated_at=float(data.get("updated_at", p.stat().st_mtime)),
                path=p,
            )
        )
    metas.sort(key=lambda m: m.updated_at, reverse=True)
    return metas


def delete_session(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def group_sessions(metas: list[SessionMeta]) -> dict[str, list[SessionMeta]]:
    """Group sessions into Today / Yesterday / This week / Previous."""
    groups: dict[str, list[SessionMeta]] = {
        "Today": [],
        "Yesterday": [],
        "This week": [],
        "Previous": [],
    }
    now = time.time()
    for m in metas:
        groups[m.date_group(now)].append(m)
    return {k: v for k, v in groups.items() if v}
