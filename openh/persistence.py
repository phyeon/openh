"""Legacy JSON session persistence helpers.

This module mirrors the public `sessions/*.json` helpers more closely than the
main transcript runtime in `cc_compat.py`, but it is still a compatibility
layer for older OpenH surfaces rather than the primary engine path.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .messages import Block, Message, TextBlock, ToolResultBlock, ToolUseBlock


SESSIONS_DIR = Path.home() / ".openh" / "sessions"


def sessions_dir() -> Path:
    return SESSIONS_DIR


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
    sessions_dir().mkdir(parents=True, exist_ok=True)


def session_path(session_id: str) -> Path:
    return sessions_dir() / f"{session_id}.json"


def new_session_id() -> str:
    return str(uuid.uuid4())


def _block_to_dict(block: Block) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        d: dict[str, Any] = {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
        if block._raw_part is not None:
            try:
                d["_raw_part_json"] = block._raw_part.to_json_dict()
            except Exception:
                pass
        return d
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
        raw_part = None
        raw_part_json = d.get("_raw_part_json")
        if raw_part_json:
            try:
                from google.genai import types as gtypes
                raw_part = gtypes.Part.model_validate(raw_part_json)
            except Exception:
                pass
        return ToolUseBlock(
            id=d.get("id", ""),
            name=d.get("name", ""),
            input=d.get("input", {}) or {},
            _raw_part=raw_part,
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
    raw_content = d.get("content", []) or []
    if isinstance(raw_content, str):
        if raw_content:
            blocks.append(TextBlock(text=raw_content))
    else:
        for bd in raw_content:
            if isinstance(bd, dict):
                b = _dict_to_block(bd)
                if b is not None:
                    blocks.append(b)
            elif isinstance(bd, str):
                blocks.append(TextBlock(text=bd))
    return Message(role=role, content=blocks, uuid=d.get("uuid"))


def _load_session_json(path_or_id: str | Path) -> tuple[Path, dict[str, Any]]:
    path = path_or_id if isinstance(path_or_id, Path) else session_path(path_or_id)
    data = json.loads(path.read_text(encoding="utf-8"))
    return path, data


def _write_session_json(path: Path, data: dict[str, Any]) -> Path:
    ensure_dir()
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_session(
    session_id: str,
    title: str,
    messages: list[Message],
    in_tokens: int,
    out_tokens: int,
    model: str,
    provider_name: str,
    created_at: float | None = None,
    *,
    tags: list[str] | None = None,
    working_dir: str | None = None,
    branch_from: str | None = None,
    branch_at_message: int | None = None,
) -> Path:
    now = time.time()
    path = session_path(session_id)
    data = {
        "session_id": session_id,
        "id": session_id,
        "title": title,
        "created_at": created_at or now,
        "updated_at": now,
        "provider": provider_name,
        "model": model,
        "in_tokens": in_tokens,
        "out_tokens": out_tokens,
        "total_tokens": int(in_tokens or 0) + int(out_tokens or 0),
        "total_cost": 0.0,
        "working_dir": working_dir or "",
        "tags": list(tags or []),
        "branch_from": branch_from,
        "branch_at_message": branch_at_message,
        "messages": [message_to_dict(m) for m in messages],
    }
    return _write_session_json(path, data)


def load_session(path_or_id: str | Path) -> tuple[dict[str, Any], list[Message]]:
    _, data = _load_session_json(path_or_id)
    messages: list[Message] = []
    for md in data.get("messages", []) or []:
        m = dict_to_message(md)
        if m is not None:
            messages.append(m)
    return data, messages


def list_sessions() -> list[SessionMeta]:
    ensure_dir()
    metas: list[SessionMeta] = []
    for p in sessions_dir().glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        metas.append(
            SessionMeta(
                session_id=str(data.get("session_id", data.get("id", p.stem))),
                title=str(data.get("title", "Untitled") or "Untitled"),
                created_at=float(data.get("created_at", p.stat().st_mtime)),
                updated_at=float(data.get("updated_at", p.stat().st_mtime)),
                path=p,
            )
        )
    metas.sort(key=lambda m: m.updated_at, reverse=True)
    return metas


def delete_session(path_or_id: str | Path) -> None:
    path = path_or_id if isinstance(path_or_id, Path) else session_path(path_or_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def rename_session(session_id: str, new_title: str) -> None:
    path, data = _load_session_json(session_id)
    data["title"] = new_title
    data["updated_at"] = time.time()
    _write_session_json(path, data)


def tag_session(session_id: str, tag: str) -> None:
    path, data = _load_session_json(session_id)
    tags = [str(t) for t in (data.get("tags", []) or [])]
    if tag not in tags:
        tags.append(tag)
        data["tags"] = tags
        data["updated_at"] = time.time()
        _write_session_json(path, data)


def untag_session(session_id: str, tag: str) -> None:
    path, data = _load_session_json(session_id)
    tags = [str(t) for t in (data.get("tags", []) or [])]
    new_tags = [t for t in tags if t != tag]
    if new_tags != tags:
        data["tags"] = new_tags
        data["updated_at"] = time.time()
        _write_session_json(path, data)


def search_sessions(query: str) -> list[dict[str, Any]]:
    lower_query = query.lower()
    results: list[dict[str, Any]] = []
    for meta in list_sessions():
        try:
            _, data = _load_session_json(meta.path)
        except Exception:
            continue
        title = str(data.get("title", "") or "")
        tags = [str(t) for t in (data.get("tags", []) or [])]
        if title.lower().find(lower_query) >= 0 or any(
            lower_query in tag.lower() for tag in tags
        ):
            results.append(data)
    results.sort(key=lambda item: float(item.get("updated_at", 0.0) or 0.0), reverse=True)
    return results


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
