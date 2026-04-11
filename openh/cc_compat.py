"""Claude Code compatibility layer.

Claude Code stores everything under ~/.claude/ with a very specific layout:

    ~/.claude/
    ├── settings.json                      # global settings
    ├── projects/<path-hash>/              # per-workspace directory
    │   ├── <session-uuid>.jsonl           # session transcript
    │   ├── <session-uuid>/                # session metadata (todos, etc.)
    │   └── memory/                        # project-scoped memdir
    │       ├── MEMORY.md                  # index
    │       └── <memory>.md                # individual memory files
    ├── plans/<name>.md                    # plan files
    ├── skills/<skill>/SKILL.md            # user-defined skills
    └── todos/<uuid>-agent-<uuid>.json     # todo list snapshots

`<path-hash>` is just the absolute cwd with '/' replaced by '-'.

This module provides the path calculations and JSONL session read/write so
openh can share the exact directory layout with Claude Code. A session file
written by openh can be resumed by Claude Code, and vice versa.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .messages import (
    Block,
    DocumentBlock,
    ImageBlock,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

OPENH_DIR = Path.home() / ".openh"
PROJECTS_DIR = OPENH_DIR / "sessions"
PLANS_DIR = OPENH_DIR / "plans"
SKILLS_DIR = OPENH_DIR / "skills"
TODOS_DIR = OPENH_DIR / "todos"

OPENH_VERSION = "0.1.0"   # shows up in JSONL `version` field
OPENH_ENTRYPOINT = "openh"


# ============================================================================
# Path helpers
# ============================================================================

def path_hash(cwd: str) -> str:
    """Turn an absolute path into Claude Code's project dir name.

    /Users/hyeon/Projects -> -Users-hyeon-Projects
    """
    abs_path = os.path.abspath(cwd)
    return abs_path.replace(os.sep, "-")


def project_dir(cwd: str) -> Path:
    return PROJECTS_DIR / path_hash(cwd)


def session_jsonl_path(cwd: str, session_id: str) -> Path:
    return project_dir(cwd) / f"{session_id}.jsonl"


def memory_dir(cwd: str) -> Path:
    return project_dir(cwd) / "memory"


def memory_index_file(cwd: str) -> Path:
    return memory_dir(cwd) / "MEMORY.md"


def ensure_project_dirs(cwd: str) -> None:
    project_dir(cwd).mkdir(parents=True, exist_ok=True)
    memory_dir(cwd).mkdir(parents=True, exist_ok=True)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    TODOS_DIR.mkdir(parents=True, exist_ok=True)


def new_session_uuid() -> str:
    """Claude Code uses plain uuid4 for session IDs."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 with millisecond precision and Z suffix, matching Claude Code."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{int(datetime.now(timezone.utc).microsecond / 1000):03d}Z"


def git_branch(cwd: str) -> str:
    try:
        import subprocess
        r = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            return r.stdout.strip() or "HEAD"
    except Exception:
        pass
    return ""


# ============================================================================
# JSONL session schema
# ============================================================================

@dataclass
class JsonlEntry:
    """A single line in a Claude Code session JSONL file."""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def type(self) -> str:
        return self.raw.get("type", "")

    @property
    def uuid(self) -> str:
        return self.raw.get("uuid", "")

    @property
    def parent_uuid(self) -> str | None:
        return self.raw.get("parentUuid")


def _block_to_cc_dict(block: Block) -> dict[str, Any]:
    """Our internal Block → Claude Code content block dict (Anthropic format)."""
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
    if isinstance(block, ImageBlock):
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": block.media_type,
                "data": block.data_base64,
            },
        }
    if isinstance(block, DocumentBlock):
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": block.media_type,
                "data": block.data_base64,
            },
        }
    return {"type": "unknown"}


def _cc_dict_to_block(d: dict[str, Any]) -> Block | None:
    """Claude Code content block dict → our internal Block."""
    t = d.get("type")
    if t == "text":
        return TextBlock(text=d.get("text", ""))
    if t == "tool_use":
        return ToolUseBlock(
            id=d.get("id", ""),
            name=d.get("name", ""),
            input=d.get("input") or {},
        )
    if t == "tool_result":
        content = d.get("content", "")
        # Claude Code sometimes nests content as a list of blocks
        if isinstance(content, list):
            parts: list[str] = []
            for sub in content:
                if isinstance(sub, dict) and sub.get("type") == "text":
                    parts.append(sub.get("text", ""))
                elif isinstance(sub, str):
                    parts.append(sub)
            content = "\n".join(parts)
        return ToolResultBlock(
            tool_use_id=d.get("tool_use_id", ""),
            content=str(content),
            is_error=bool(d.get("is_error", False)),
        )
    if t == "image":
        src = d.get("source") or {}
        return ImageBlock(
            data_base64=src.get("data", ""),
            media_type=src.get("media_type", "image/png"),
        )
    if t == "document":
        src = d.get("source") or {}
        return DocumentBlock(
            data_base64=src.get("data", ""),
            media_type=src.get("media_type", "application/pdf"),
        )
    return None


# ============================================================================
# JSONL session writer
# ============================================================================

class JsonlSessionWriter:
    """Append entries to a Claude Code-compatible JSONL session file.

    One writer per session. Safe to call from a long-running process — each
    append opens + writes + closes to survive crashes.
    """

    def __init__(self, cwd: str, session_id: str) -> None:
        self.cwd = cwd
        self.session_id = session_id
        self.path = session_jsonl_path(cwd, session_id)
        self._last_uuid: str | None = None
        ensure_project_dirs(cwd)

    def _base_envelope(self) -> dict[str, Any]:
        return {
            "parentUuid": self._last_uuid,
            "isSidechain": False,
            "sessionId": self.session_id,
            "timestamp": now_iso(),
            "cwd": self.cwd,
            "version": OPENH_VERSION,
            "entrypoint": OPENH_ENTRYPOINT,
            "userType": "external",
            "permissionMode": "default",
            "gitBranch": git_branch(self.cwd),
        }

    def append_user(self, message: Message) -> str:
        """Append a user-role message. Returns its uuid."""
        envelope = self._base_envelope()
        envelope.update({
            "type": "user",
            "uuid": str(uuid.uuid4()),
            "promptId": str(uuid.uuid4()),
            "message": {
                "role": "user",
                "content": [_block_to_cc_dict(b) for b in message.content],
            },
        })
        self._write_entry(envelope)
        self._last_uuid = envelope["uuid"]
        return envelope["uuid"]

    def append_assistant(self, message: Message) -> str:
        """Append an assistant-role message. Returns its uuid."""
        envelope = self._base_envelope()
        envelope.update({
            "type": "assistant",
            "uuid": str(uuid.uuid4()),
            "message": {
                "role": "assistant",
                "content": [_block_to_cc_dict(b) for b in message.content],
            },
        })
        self._write_entry(envelope)
        self._last_uuid = envelope["uuid"]
        return envelope["uuid"]

    def append_raw(self, entry: dict[str, Any]) -> None:
        self._write_entry(entry)

    def _write_entry(self, entry: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ============================================================================
# JSONL session reader
# ============================================================================

def read_session_jsonl(path: Path) -> tuple[list[Message], dict[str, Any]]:
    """Parse a Claude Code JSONL session file.

    Returns (messages, metadata) where metadata captures the last known
    sessionId, cwd, gitBranch etc.
    """
    messages: list[Message] = []
    metadata: dict[str, Any] = {"session_id": path.stem, "cwd": "", "gitBranch": ""}

    if not path.exists():
        return messages, metadata

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            entry_type = obj.get("type")
            if "sessionId" in obj:
                metadata["session_id"] = obj["sessionId"]
            if "cwd" in obj:
                metadata["cwd"] = obj["cwd"]
            if "gitBranch" in obj:
                metadata["gitBranch"] = obj["gitBranch"]

            if entry_type == "__meta__":
                # Merge __meta__ fields into metadata (last wins)
                for k, v in obj.items():
                    if k != "type":
                        metadata[k] = v
                continue

            if entry_type in ("user", "assistant"):
                msg_field = obj.get("message") or {}
                role = msg_field.get("role")
                if role not in ("user", "assistant"):
                    continue
                raw_content = msg_field.get("content")
                blocks: list[Block] = []
                if isinstance(raw_content, str):
                    if raw_content:
                        blocks.append(TextBlock(text=raw_content))
                elif isinstance(raw_content, list):
                    for bd in raw_content:
                        if isinstance(bd, dict):
                            b = _cc_dict_to_block(bd)
                            if b is not None:
                                blocks.append(b)
                        elif isinstance(bd, str):
                            blocks.append(TextBlock(text=bd))
                if blocks:
                    messages.append(Message(role=role, content=blocks))

    return messages, metadata


# ============================================================================
# Session listing
# ============================================================================

@dataclass
class CCSessionMeta:
    """Metadata for a discovered Claude Code session."""
    session_id: str
    path: Path
    cwd: str
    mtime: float
    size: int
    title: str = ""         # derived from first user turn (best-effort)
    starred: bool = False
    hidden: bool = False

    def date_group(self, now: float | None = None) -> str:
        import time
        now = now or time.time()
        delta = now - self.mtime
        if delta < 24 * 3600:
            return "Today"
        if delta < 48 * 3600:
            return "Yesterday"
        if delta < 7 * 24 * 3600:
            return "This week"
        return "Previous"


def list_sessions_for_cwd(cwd: str) -> list[CCSessionMeta]:
    """All .jsonl files in the project dir for the given cwd."""
    d = project_dir(cwd)
    if not d.exists():
        return []
    metas: list[CCSessionMeta] = []
    for p in d.glob("*.jsonl"):
        try:
            stat = p.stat()
        except OSError:
            continue
        # Peek title from first user message (expensive but only at listing time)
        title = _peek_title(p)
        metas.append(
            CCSessionMeta(
                session_id=p.stem,
                path=p,
                cwd=cwd,
                mtime=stat.st_mtime,
                size=stat.st_size,
                title=title,
            )
        )
    metas.sort(key=lambda m: m.mtime, reverse=True)
    return metas


def list_all_projects() -> list[Path]:
    if not PROJECTS_DIR.exists():
        return []
    return sorted([p for p in PROJECTS_DIR.iterdir() if p.is_dir()])


def list_all_recent_sessions(limit: int = 60) -> list[CCSessionMeta]:
    """All sessions across every ~/.claude/projects/ directory, newest first.

    Reads every .jsonl file's stat in one pass (fast), then peeks the first
    user message for title + cwd on only the top `limit` results (slower).
    """
    if not PROJECTS_DIR.exists():
        return []

    rough: list[tuple[Path, float, int, Path]] = []
    for proj_dir in PROJECTS_DIR.iterdir():
        if not proj_dir.is_dir():
            continue
        for p in proj_dir.glob("*.jsonl"):
            try:
                stat = p.stat()
            except OSError:
                continue
            rough.append((p, stat.st_mtime, stat.st_size, proj_dir))

    rough.sort(key=lambda t: t[1], reverse=True)
    top = rough[:limit]

    metas: list[CCSessionMeta] = []
    for path, mtime, size, proj_dir in top:
        cwd, title = _peek_cwd_and_title(path)
        if not cwd:
            cwd = _unhash_project_dir_name(proj_dir.name)
        metas.append(
            CCSessionMeta(
                session_id=path.stem,
                path=path,
                cwd=cwd,
                mtime=mtime,
                size=size,
                title=title,
            )
        )
    return metas


def _peek_cwd_and_title(path: Path) -> tuple[str, str]:
    """Read the session file to find cwd and title.

    Checks __meta__ title (last one wins), skips <environment> blocks.
    """
    def skip_title(text: str) -> bool:
        return text.startswith("[Conversation compacted") or text.startswith("[Prior conversation summary")

    cwd = ""
    first_user_title = ""
    explicit_title = ""
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not cwd and isinstance(obj.get("cwd"), str):
                    cwd = obj["cwd"]
                if obj.get("type") == "__meta__" and obj.get("title"):
                    explicit_title = obj["title"][:70]
                    continue
                if not first_user_title and obj.get("type") == "user":
                    msg = obj.get("message") or {}
                    content = msg.get("content")
                    if isinstance(content, str):
                        text = content.strip()
                        if not text.startswith("<environment>") and not skip_title(text) and text:
                            first_user_title = text.splitlines()[0][:70]
                    elif isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "text":
                                t = (b.get("text") or "").strip()
                                if t.startswith("<environment>") or skip_title(t):
                                    continue
                                if t:
                                    first_user_title = t.splitlines()[0][:70]
                                    break
    except OSError:
        pass
    return cwd, explicit_title or first_user_title


def _unhash_project_dir_name(name: str) -> str:
    """Best-effort reverse of path_hash() — used only for display."""
    if not name.startswith("-"):
        return name
    return "/" + "/".join(name.lstrip("-").split("-"))


def _peek_title(path: Path) -> str:
    """Read user text messages and return the first real one as a title.

    Skips system-injected <environment> blocks.
    Also checks for an explicit __title__ metadata line.
    """
    def skip_title(text: str) -> bool:
        return text.startswith("[Conversation compacted") or text.startswith("[Prior conversation summary")

    try:
        explicit_title = ""
        first_user_title = ""
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Explicit title metadata (written by rename) — last one wins
                if obj.get("type") == "__meta__" and obj.get("title"):
                    explicit_title = obj["title"][:70]
                    continue
                if first_user_title or obj.get("type") != "user":
                    continue
                msg = obj.get("message") or {}
                content = msg.get("content")
                if isinstance(content, str):
                    text = content.strip()
                    if text.startswith("<environment>") or skip_title(text):
                        continue
                    if text:
                        first_user_title = text.splitlines()[0][:70]
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "text":
                            text = (b.get("text") or "").strip()
                            if text.startswith("<environment>") or skip_title(text):
                                continue
                            if text:
                                first_user_title = text.splitlines()[0][:70]
                                break
        return explicit_title or first_user_title or "(untitled)"
    except OSError:
        pass
    return "(untitled)"


def save_session_title(path: Path, title: str) -> None:
    """Append a __meta__ line with the explicit title to the JSONL file."""
    save_session_meta(path, title=title)


def save_session_meta(
    path: Path,
    *,
    title: str | None = None,
    total_input_tokens: int | None = None,
    total_output_tokens: int | None = None,
    last_input_tokens: int | None = None,
    total_estimated_cost_usd: float | None = None,
    session_cwd: str | None = None,
    prompt_override: str | None = None,
) -> None:
    """Append a __meta__ line with session metadata to the JSONL file."""
    meta: dict[str, Any] = {"type": "__meta__"}
    if title is not None:
        meta["title"] = title
    if total_input_tokens is not None:
        meta["total_input_tokens"] = total_input_tokens
    if total_output_tokens is not None:
        meta["total_output_tokens"] = total_output_tokens
    if last_input_tokens is not None:
        meta["last_input_tokens"] = last_input_tokens
    if total_estimated_cost_usd is not None:
        meta["total_estimated_cost_usd"] = round(total_estimated_cost_usd, 8)
    if session_cwd is not None:
        meta["session_cwd"] = session_cwd
    if prompt_override is not None:
        meta["prompt_override"] = prompt_override
    line = json.dumps(meta, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_session_meta(path: Path) -> dict[str, Any]:
    """Read all __meta__ lines and merge them (last value wins)."""
    merged: dict[str, Any] = {}
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "__meta__":
                    for k, v in obj.items():
                        if k != "type":
                            merged[k] = v
    except OSError:
        pass
    return merged


def group_sessions(metas: list[CCSessionMeta]) -> dict[str, list[CCSessionMeta]]:
    groups: dict[str, list[CCSessionMeta]] = {
        "Today": [],
        "Yesterday": [],
        "This week": [],
        "Previous": [],
    }
    import time
    now = time.time()
    for m in metas:
        groups[m.date_group(now)].append(m)
    return {k: v for k, v in groups.items() if v}


# ============================================================================
#  Session flags (starred / hidden) — stored in ~/.openh/session_flags.json
# ============================================================================

_FLAGS_PATH = Path.home() / ".openh" / "session_flags.json"


def _load_flags() -> dict[str, dict[str, bool]]:
    if not _FLAGS_PATH.exists():
        return {}
    try:
        return json.loads(_FLAGS_PATH.read_text("utf-8"))
    except Exception:
        return {}


def _save_flags(flags: dict[str, dict[str, bool]]) -> None:
    _FLAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FLAGS_PATH.write_text(json.dumps(flags, indent=2), "utf-8")


def apply_flags(metas: list[CCSessionMeta]) -> list[CCSessionMeta]:
    """Annotate metas with starred/hidden from disk."""
    flags = _load_flags()
    for m in metas:
        f = flags.get(m.session_id, {})
        m.starred = f.get("starred", False)
        m.hidden = f.get("hidden", False)
    return metas


def set_session_flag(session_id: str, *, starred: bool | None = None, hidden: bool | None = None) -> None:
    flags = _load_flags()
    entry = flags.get(session_id, {})
    if starred is not None:
        entry["starred"] = starred
    if hidden is not None:
        entry["hidden"] = hidden
    flags[session_id] = entry
    _save_flags(flags)
