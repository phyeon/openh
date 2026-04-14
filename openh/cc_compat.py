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

`<path-hash>` is the project root encoded as URL-safe base64 without padding.

This module provides the path calculations and JSONL session read/write so
openh can share the exact directory layout with Claude Code. A session file
written by openh can be resumed by Claude Code, and vice versa.
"""
from __future__ import annotations

import base64
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
PROJECTS_DIR = OPENH_DIR / "projects"
LEGACY_PROJECTS_DIR = OPENH_DIR / "sessions"
PLANS_DIR = OPENH_DIR / "plans"
SKILLS_DIR = OPENH_DIR / "skills"
TODOS_DIR = OPENH_DIR / "todos"
MAX_TRANSCRIPT_BYTES = 50 * 1024 * 1024
TAIL_READ_BYTES = 65_536

OPENH_VERSION = "0.1.0"   # shows up in JSONL `version` field
OPENH_ENTRYPOINT = "openh"


# ============================================================================
# Path helpers
# ============================================================================

def path_hash(cwd: str) -> str:
    """Turn an absolute path into the public transcript dir encoding."""
    abs_path = os.path.abspath(cwd)
    return base64.urlsafe_b64encode(abs_path.encode("utf-8")).decode("ascii").rstrip("=")


def _legacy_path_hash(cwd: str) -> str:
    abs_path = os.path.abspath(cwd)
    return abs_path.replace(os.sep, "-").replace(":", "")


def _canonical_project_dir(cwd: str) -> Path:
    return PROJECTS_DIR / path_hash(cwd)


def _legacy_project_dir(cwd: str) -> Path:
    return LEGACY_PROJECTS_DIR / _legacy_path_hash(cwd)


def _project_dir_candidates(cwd: str) -> list[Path]:
    candidates: list[Path] = []
    for candidate in (_canonical_project_dir(cwd), _legacy_project_dir(cwd)):
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def project_dir(cwd: str) -> Path:
    primary = _canonical_project_dir(cwd)
    legacy = _legacy_project_dir(cwd)
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    return primary


def session_jsonl_path(cwd: str, session_id: str) -> Path:
    filename = f"{session_id}.jsonl"
    for candidate in _project_dir_candidates(cwd):
        existing = candidate / filename
        if existing.exists():
            return existing
    return _canonical_project_dir(cwd) / filename


def memory_dir(cwd: str) -> Path:
    primary = _canonical_project_dir(cwd) / "memory"
    legacy = _legacy_project_dir(cwd) / "memory"
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    return primary


def memory_index_file(cwd: str) -> Path:
    return memory_dir(cwd) / "MEMORY.md"


def ensure_project_dirs(cwd: str) -> None:
    _canonical_project_dir(cwd).mkdir(parents=True, exist_ok=True)
    (_canonical_project_dir(cwd) / "memory").mkdir(parents=True, exist_ok=True)
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


def _extract_message_text(message: Message) -> str:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            text = block.text.strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts).strip()


def _append_jsonl_entry(path: Path, entry: dict[str, Any]) -> None:
    try:
        if path.exists() and path.stat().st_size >= MAX_TRANSCRIPT_BYTES:
            return
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _read_tail_text(path: Path) -> str:
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    if size <= 0:
        return ""
    offset = max(0, size - TAIL_READ_BYTES)
    try:
        with path.open("rb") as f:
            f.seek(offset)
            return f.read().decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _read_last_chain_uuid(path: Path) -> str | None:
    text = _read_tail_text(path)
    if not text:
        return None
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") not in ("user", "assistant"):
            continue
        msg_field = obj.get("message") or {}
        msg_uuid = obj.get("uuid") or msg_field.get("uuid")
        if isinstance(msg_uuid, str) and msg_uuid:
            return msg_uuid
    return None


def _read_tail_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {
        "cwd": "",
        "title": "",
        "last_prompt": "",
        "profile_id": "",
    }
    text = _read_tail_text(path)
    if not text:
        return metadata

    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not metadata["cwd"]:
            for key in ("session_cwd", "cwd"):
                val = obj.get(key)
                if isinstance(val, str) and val:
                    metadata["cwd"] = val
                    break

        entry_type = obj.get("type")
        if not metadata["title"]:
            if entry_type == "custom-title":
                val = obj.get("customTitle") or obj.get("custom_title")
                if isinstance(val, str) and val:
                    metadata["title"] = val[:70]
            elif entry_type == "__meta__":
                val = obj.get("title")
                if isinstance(val, str) and val:
                    metadata["title"] = val[:70]

        if not metadata["last_prompt"] and entry_type == "last-prompt":
            val = obj.get("lastPrompt") or obj.get("last_prompt")
            if isinstance(val, str) and val:
                metadata["last_prompt"] = val

        if not metadata["profile_id"] and entry_type == "__meta__":
            val = obj.get("profile_id")
            if isinstance(val, str) and val:
                metadata["profile_id"] = val

        if all(metadata.values()):
            break

    return metadata


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
            input=d.get("input") or {},
            _raw_part=raw_part,
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
        ensure_project_dirs(cwd)
        self._last_uuid: str | None = _read_last_chain_uuid(self.path)

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
        msg_uuid = message.uuid or str(uuid.uuid4())
        message.uuid = msg_uuid
        envelope = self._base_envelope()
        envelope.update({
            "type": "user",
            "uuid": msg_uuid,
            "promptId": str(uuid.uuid4()),
            "message": {
                "role": "user",
                "content": [_block_to_cc_dict(b) for b in message.content],
            },
        })
        self._write_entry(envelope)
        self._last_uuid = envelope["uuid"]
        prompt_text = _extract_message_text(message)
        if prompt_text:
            self._write_entry(
                {
                    "type": "last-prompt",
                    "sessionId": self.session_id,
                    "lastPrompt": prompt_text,
                }
            )
        return envelope["uuid"]

    def append_assistant(self, message: Message) -> str:
        """Append an assistant-role message. Returns its uuid."""
        msg_uuid = message.uuid or str(uuid.uuid4())
        message.uuid = msg_uuid
        envelope = self._base_envelope()
        envelope.update({
            "type": "assistant",
            "uuid": msg_uuid,
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
        _append_jsonl_entry(self.path, entry)


# ============================================================================
# JSONL session reader
# ============================================================================

def read_session_jsonl(path: Path) -> tuple[list[Message], dict[str, Any]]:
    """Parse a Claude Code JSONL session file.

    Returns (messages, metadata) where metadata captures the last known
    sessionId, cwd, gitBranch etc.
    """
    messages: list[Message] = []
    metadata: dict[str, Any] = {
        "session_id": path.stem,
        "cwd": "",
        "gitBranch": "",
        "title": "",
        "last_prompt": "",
    }

    if not path.exists():
        return messages, metadata

    try:
        if path.stat().st_size > MAX_TRANSCRIPT_BYTES:
            metadata.update(_read_tail_metadata(path))
            return messages, metadata
    except OSError:
        return messages, metadata

    tombstoned: set[str] = set()
    entries: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            entries.append(obj)
            if obj.get("type") == "tombstone":
                deleted_uuid = obj.get("deletedUuid") or obj.get("deleted_uuid")
                if isinstance(deleted_uuid, str) and deleted_uuid:
                    tombstoned.add(deleted_uuid)

    for obj in entries:
        entry_type = obj.get("type")
        if "sessionId" in obj:
            metadata["session_id"] = obj["sessionId"]
        if "cwd" in obj:
            metadata["cwd"] = obj["cwd"]
        if "gitBranch" in obj:
            metadata["gitBranch"] = obj["gitBranch"]

        if entry_type == "__meta__":
            for k, v in obj.items():
                if k != "type":
                    metadata[k] = v
            continue

        if entry_type == "custom-title":
            title = obj.get("customTitle") or obj.get("custom_title")
            if isinstance(title, str) and title:
                metadata["title"] = title[:70]
            continue

        if entry_type == "last-prompt":
            last_prompt = obj.get("lastPrompt") or obj.get("last_prompt")
            if isinstance(last_prompt, str) and last_prompt:
                metadata["last_prompt"] = last_prompt
            continue

        if entry_type == "tombstone":
            continue

        if entry_type in ("user", "assistant"):
            msg_field = obj.get("message") or {}
            role = msg_field.get("role")
            if role not in ("user", "assistant"):
                continue
            msg_uuid = obj.get("uuid") or msg_field.get("uuid")
            if isinstance(msg_uuid, str) and msg_uuid and msg_uuid in tombstoned:
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
                messages.append(
                    Message(
                        role=role,
                        content=blocks,
                        uuid=msg_uuid,
                    )
                )

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
    profile_id: str = "default"

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
    metas: list[CCSessionMeta] = []
    seen_paths: set[Path] = set()
    for d in _project_dir_candidates(cwd):
        if not d.exists():
            continue
        for p in d.glob("*.jsonl"):
            if p in seen_paths:
                continue
            seen_paths.add(p)
            try:
                stat = p.stat()
            except OSError:
                continue
            tail = _read_tail_metadata(p)
            title = tail["title"] or _peek_title(p)
            pid = tail["profile_id"] or "default"
            metas.append(
                CCSessionMeta(
                    session_id=p.stem,
                    path=p,
                    cwd=tail["cwd"] or cwd,
                    mtime=stat.st_mtime,
                    size=stat.st_size,
                    title=title,
                    profile_id=pid,
                )
            )
    metas.sort(key=lambda m: m.mtime, reverse=True)
    return metas


def list_all_projects() -> list[Path]:
    projects: list[Path] = []
    for root in (PROJECTS_DIR, LEGACY_PROJECTS_DIR):
        if not root.exists():
            continue
        for path in root.iterdir():
            if path.is_dir() and path not in projects:
                projects.append(path)
    return sorted(projects)


def list_all_recent_sessions(limit: int = 60) -> list[CCSessionMeta]:
    """All sessions across every ~/.claude/projects/ directory, newest first.

    Reads every .jsonl file's stat in one pass (fast), then peeks the first
    user message for title + cwd on only the top `limit` results (slower).
    """
    if not PROJECTS_DIR.exists() and not LEGACY_PROJECTS_DIR.exists():
        return []

    rough: list[tuple[Path, float, int, Path]] = []
    for root in (PROJECTS_DIR, LEGACY_PROJECTS_DIR):
        if not root.exists():
            continue
        for proj_dir in root.iterdir():
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
    seen_session_ids: set[str] = set()
    for path, mtime, size, proj_dir in top:
        if path.stem in seen_session_ids:
            continue
        seen_session_ids.add(path.stem)
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

    tail = _read_tail_metadata(path)
    cwd = tail["cwd"]
    first_user_title = ""
    explicit_title = tail["title"]
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not cwd:
                    for key in ("session_cwd", "cwd"):
                        val = obj.get(key)
                        if isinstance(val, str) and val:
                            cwd = val
                            break
                if obj.get("type") == "__meta__" and obj.get("title"):
                    explicit_title = str(obj["title"])[:70]
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
    """Best-effort reverse of project dir encoding — used only for display."""
    padded = name + "=" * (-len(name) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        if not name.startswith("-"):
            return name
        return "/" + "/".join(name.lstrip("-").split("-"))
    return decoded


def _peek_profile_id(path: Path) -> str:
    """Read __meta__ lines to find profile_id. Returns 'default' if not found."""
    tail = _read_tail_metadata(path)
    if tail["profile_id"]:
        return tail["profile_id"]
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "__meta__" and obj.get("profile_id"):
                    return obj["profile_id"]
    except OSError:
        pass
    return "default"


def _peek_title(path: Path) -> str:
    """Read user text messages and return the first real one as a title.

    Skips system-injected <environment> blocks.
    Also checks for an explicit __title__ metadata line.
    """
    def skip_title(text: str) -> bool:
        return text.startswith("[Conversation compacted") or text.startswith("[Prior conversation summary")

    try:
        explicit_title = _read_tail_metadata(path)["title"]
        first_user_title = ""
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # Explicit title metadata (written by rename) — last one wins
                if obj.get("type") == "__meta__":
                    if obj.get("title"):
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
    """Append public + local title metadata to the JSONL file."""
    _append_jsonl_entry(
        path,
        {
            "type": "custom-title",
            "sessionId": path.stem,
            "customTitle": title,
        },
    )
    save_session_meta(path, title=title)


def tombstone_entry(path: Path, uuid: str) -> None:
    """Append a public tombstone entry for a deleted transcript message."""
    _append_jsonl_entry(
        path,
        {
            "type": "tombstone",
            "deletedUuid": uuid,
        },
    )


def save_session_meta(
    path: Path,
    *,
    title: str | None = None,
    total_input_tokens: int | None = None,
    total_output_tokens: int | None = None,
    total_cache_creation_input_tokens: int | None = None,
    total_cache_read_input_tokens: int | None = None,
    subagent_total_input_tokens: int | None = None,
    subagent_total_output_tokens: int | None = None,
    subagent_total_cache_creation_input_tokens: int | None = None,
    subagent_total_cache_read_input_tokens: int | None = None,
    last_input_tokens: int | None = None,
    total_estimated_cost_usd: float | None = None,
    subagent_total_estimated_cost_usd: float | None = None,
    usage_by_model: dict[str, dict[str, int | float]] | None = None,
    session_cwd: str | None = None,
    prompt_override: str | None = None,
    profile_id: str | None = None,
    output_style: str | None = None,
    output_style_prompt: str | None = None,
    append_system_prompt: str | None = None,
    replace_system_prompt: bool | None = None,
    coordinator_mode: bool | None = None,
    session_memory_last_extracted_message_uuid: str | None = None,
    session_memory_last_extracted_message_count: int | None = None,
    session_memory_last_extracted_tool_call_count: int | None = None,
) -> None:
    """Append a __meta__ line with session metadata to the JSONL file."""
    meta: dict[str, Any] = {"type": "__meta__"}
    if title is not None:
        meta["title"] = title
    if total_input_tokens is not None:
        meta["total_input_tokens"] = total_input_tokens
    if total_output_tokens is not None:
        meta["total_output_tokens"] = total_output_tokens
    if total_cache_creation_input_tokens is not None:
        meta["total_cache_creation_input_tokens"] = total_cache_creation_input_tokens
    if total_cache_read_input_tokens is not None:
        meta["total_cache_read_input_tokens"] = total_cache_read_input_tokens
    if subagent_total_input_tokens is not None:
        meta["subagent_total_input_tokens"] = subagent_total_input_tokens
    if subagent_total_output_tokens is not None:
        meta["subagent_total_output_tokens"] = subagent_total_output_tokens
    if subagent_total_cache_creation_input_tokens is not None:
        meta["subagent_total_cache_creation_input_tokens"] = (
            subagent_total_cache_creation_input_tokens
        )
    if subagent_total_cache_read_input_tokens is not None:
        meta["subagent_total_cache_read_input_tokens"] = (
            subagent_total_cache_read_input_tokens
        )
    if last_input_tokens is not None:
        meta["last_input_tokens"] = last_input_tokens
    if total_estimated_cost_usd is not None:
        meta["total_estimated_cost_usd"] = round(total_estimated_cost_usd, 8)
    if subagent_total_estimated_cost_usd is not None:
        meta["subagent_total_estimated_cost_usd"] = round(
            subagent_total_estimated_cost_usd,
            8,
        )
    if usage_by_model is not None:
        sanitized: dict[str, dict[str, int | float]] = {}
        for model_name, entry in usage_by_model.items():
            if not isinstance(model_name, str) or not isinstance(entry, dict):
                continue
            sanitized[model_name] = {
                "input_tokens": int(entry.get("input_tokens", 0) or 0),
                "output_tokens": int(entry.get("output_tokens", 0) or 0),
                "cache_creation_input_tokens": int(
                    entry.get("cache_creation_input_tokens", 0) or 0
                ),
                "cache_read_input_tokens": int(
                    entry.get("cache_read_input_tokens", 0) or 0
                ),
                "cost_usd": round(float(entry.get("cost_usd", 0.0) or 0.0), 8),
                "requests": int(entry.get("requests", 0) or 0),
            }
        meta["usage_by_model"] = sanitized
    if session_cwd is not None:
        meta["session_cwd"] = session_cwd
    if prompt_override is not None:
        meta["prompt_override"] = prompt_override
    if profile_id is not None and profile_id != "default":
        meta["profile_id"] = profile_id
    if output_style is not None:
        meta["output_style"] = output_style
    if output_style_prompt is not None:
        meta["output_style_prompt"] = output_style_prompt
    if append_system_prompt is not None:
        meta["append_system_prompt"] = append_system_prompt
    if replace_system_prompt is not None:
        meta["replace_system_prompt"] = bool(replace_system_prompt)
    if coordinator_mode is not None:
        meta["coordinator_mode"] = bool(coordinator_mode)
    if session_memory_last_extracted_message_uuid is not None:
        meta["session_memory_last_extracted_message_uuid"] = (
            session_memory_last_extracted_message_uuid
        )
    if session_memory_last_extracted_message_count is not None:
        meta["session_memory_last_extracted_message_count"] = (
            session_memory_last_extracted_message_count
        )
    if session_memory_last_extracted_tool_call_count is not None:
        meta["session_memory_last_extracted_tool_call_count"] = (
            session_memory_last_extracted_tool_call_count
        )
    _append_jsonl_entry(path, meta)


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
    tail = _read_tail_metadata(path)
    if tail["title"] and "title" not in merged:
        merged["title"] = tail["title"]
    if tail["last_prompt"] and "last_prompt" not in merged:
        merged["last_prompt"] = tail["last_prompt"]
    if tail["cwd"] and "cwd" not in merged and "session_cwd" not in merged:
        merged["cwd"] = tail["cwd"]
    if tail["profile_id"] and "profile_id" not in merged:
        merged["profile_id"] = tail["profile_id"]
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
#  Usage aggregation — cross-session token/cost summaries
# ============================================================================


@dataclass
class UsageAggregate:
    """Aggregated usage across multiple sessions."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_input_tokens: int = 0
    total_cache_read_input_tokens: int = 0
    total_cost_usd: float = 0.0
    session_count: int = 0
    usage_by_model: dict = field(default_factory=dict)
    cost_by_date: dict = field(default_factory=dict)  # "2026-04-13" -> cost


def aggregate_usage(
    since: float = 0.0,
    until: float = 0.0,
    limit: int = 500,
) -> UsageAggregate:
    """Scan sessions and aggregate token/cost data within a date range.

    Args:
        since: Unix epoch — include sessions with mtime >= this value. 0 = no lower bound.
        until: Unix epoch — include sessions with mtime <= this value. 0 = no upper bound.
        limit: Max sessions to scan.
    """
    import time
    from datetime import datetime

    if until <= 0:
        until = time.time() + 86400  # future-proof

    sessions = list_all_recent_sessions(limit=limit)
    agg = UsageAggregate()

    for meta in sessions:
        if meta.mtime < since or meta.mtime > until:
            continue
        try:
            data = read_session_meta(meta.path)
        except Exception:
            continue

        in_tok = int(data.get("total_input_tokens", 0) or 0)
        out_tok = int(data.get("total_output_tokens", 0) or 0)
        cache_create = int(data.get("total_cache_creation_input_tokens", 0) or 0)
        cache_read = int(data.get("total_cache_read_input_tokens", 0) or 0)
        cost = float(data.get("total_estimated_cost_usd", 0) or 0)

        if in_tok == 0 and out_tok == 0 and cost == 0:
            continue

        agg.total_input_tokens += in_tok
        agg.total_output_tokens += out_tok
        agg.total_cache_creation_input_tokens += cache_create
        agg.total_cache_read_input_tokens += cache_read
        agg.total_cost_usd += cost
        agg.session_count += 1

        # Per-model breakdown
        by_model = data.get("usage_by_model")
        if isinstance(by_model, dict):
            for model_name, model_data in by_model.items():
                if not isinstance(model_data, dict):
                    continue
                existing = agg.usage_by_model.setdefault(model_name, {
                    "input_tokens": 0, "output_tokens": 0,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                    "cost_usd": 0.0, "requests": 0,
                })
                for key in ("input_tokens", "output_tokens",
                            "cache_creation_input_tokens", "cache_read_input_tokens",
                            "requests"):
                    existing[key] = existing.get(key, 0) + int(model_data.get(key, 0) or 0)
                existing["cost_usd"] = existing.get("cost_usd", 0.0) + float(
                    model_data.get("cost_usd", 0) or 0
                )

        # Per-day cost
        day_str = datetime.fromtimestamp(meta.mtime).strftime("%Y-%m-%d")
        agg.cost_by_date[day_str] = agg.cost_by_date.get(day_str, 0.0) + cost

    return agg


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
