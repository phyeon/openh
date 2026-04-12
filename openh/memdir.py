"""Memdir — persistent, file-based memory like Claude Code uses."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from time import time
from typing import Literal

from .cc_compat import memory_dir, memory_index_file

MemoryType = Literal["user", "feedback", "project", "reference"]

VALID_TYPES: tuple[MemoryType, ...] = ("user", "feedback", "project", "reference")
MEMORY_ENTRYPOINT = "MEMORY.md"
MAX_MEMORY_FILES = 200
FRONTMATTER_MAX_LINES = 30
MAX_ENTRYPOINT_LINES = 200
MAX_ENTRYPOINT_BYTES = 25_000


@dataclass
class Memory:
    name: str
    description: str
    type: MemoryType
    body: str
    path: Path | None = None


@dataclass
class MemoryFileMeta:
    filename: str
    path: Path
    name: str | None
    description: str | None
    memory_type: MemoryType | None
    modified_secs: int


@dataclass
class EntrypointTruncation:
    content: str
    line_count: int
    byte_count: int
    was_line_truncated: bool
    was_byte_truncated: bool


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _coerce_type(value: str) -> MemoryType:
    normalized = (value or "").strip().lower()
    if normalized in VALID_TYPES:
        return normalized  # type: ignore[return-value]
    return "reference"


def _parse_memory_type(value: str) -> MemoryType | None:
    normalized = (value or "").strip().lower()
    if normalized in VALID_TYPES:
        return normalized  # type: ignore[return-value]
    return None


def parse_frontmatter_quick(
    content: str,
) -> tuple[str | None, str | None, MemoryType | None]:
    name = None
    description = None
    memory_type = None

    lines = content.splitlines()[:FRONTMATTER_MAX_LINES]
    if not lines or lines[0].strip() != "---":
        return name, description, memory_type

    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("name:"):
            name = line.partition(":")[2].strip().strip('"').strip("'")
        elif line.startswith("description:"):
            description = line.partition(":")[2].strip().strip('"').strip("'")
        elif line.startswith("type:"):
            memory_type = _parse_memory_type(
                line.partition(":")[2].strip().strip('"').strip("'")
            )

    return name, description, memory_type


def parse_memory_file(path: Path) -> Memory | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    matched = _FRONTMATTER_RE.match(raw)
    if not matched:
        return Memory(
            name=path.stem,
            description="",
            type="reference",
            body=raw.strip(),
            path=path,
        )

    fm_raw, body = matched.group(1), matched.group(2)
    fields: dict[str, str] = {}
    for line in fm_raw.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip().lower()] = value.strip()

    return Memory(
        name=fields.get("name", path.stem),
        description=fields.get("description", ""),
        type=_coerce_type(fields.get("type", "reference")),
        body=body.strip(),
        path=path,
    )


def serialize_memory(mem: Memory) -> str:
    return "\n".join(
        [
            "---",
            f"name: {mem.name}",
            f"description: {mem.description}",
            f"type: {mem.type}",
            "---",
            "",
            mem.body.strip(),
            "",
        ]
    )


def safe_filename(name: str) -> str:
    value = name.strip().lower()
    value = re.sub(r"[^a-z0-9가-힣_\- ]+", "", value)
    value = re.sub(r"\s+", "_", value)
    return f"{value or 'untitled'}.md"


def ensure_dir(cwd: str) -> Path:
    target = memory_dir(cwd)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _collect_md_files(base: Path, current: Path, out: list[MemoryFileMeta]) -> None:
    try:
        entries = list(current.iterdir())
    except OSError:
        return

    for entry in entries:
        if entry.is_dir():
            _collect_md_files(base, entry, out)
            continue
        if entry.suffix != ".md" or entry.name == MEMORY_ENTRYPOINT:
            continue

        try:
            raw = entry.read_text(encoding="utf-8")
        except OSError:
            raw = ""
        name, description, memory_type = parse_frontmatter_quick(raw)
        try:
            modified_secs = int(entry.stat().st_mtime)
        except OSError:
            modified_secs = 0

        try:
            relative = entry.relative_to(base).as_posix()
        except ValueError:
            relative = entry.name

        out.append(
            MemoryFileMeta(
                filename=relative,
                path=entry,
                name=name,
                description=description,
                memory_type=memory_type,
                modified_secs=modified_secs,
            )
        )


def scan_memory_dir(dir_path: Path) -> list[MemoryFileMeta]:
    files: list[MemoryFileMeta] = []
    if not dir_path.exists():
        return files
    _collect_md_files(dir_path, dir_path, files)
    files.sort(key=lambda item: item.modified_secs, reverse=True)
    return files[:MAX_MEMORY_FILES]


def list_memories(cwd: str) -> list[Memory]:
    out: list[Memory] = []
    for meta in scan_memory_dir(memory_dir(cwd)):
        mem = parse_memory_file(meta.path)
        if mem is not None:
            out.append(mem)
    return out


def save_memory(cwd: str, mem: Memory) -> Memory:
    base = ensure_dir(cwd)
    path = base / safe_filename(mem.name)
    path.write_text(serialize_memory(mem), encoding="utf-8")
    mem.path = path
    _rewrite_index(cwd)
    return mem


def delete_memory(cwd: str, name: str) -> bool:
    deleted = False
    for meta in scan_memory_dir(memory_dir(cwd)):
        mem = parse_memory_file(meta.path)
        if mem is None:
            continue
        if mem.name.lower() != name.lower() and meta.path.stem.lower() != name.lower():
            continue
        try:
            meta.path.unlink()
            deleted = True
        except OSError:
            pass
    if deleted:
        _rewrite_index(cwd)
    return deleted


def format_unix_secs_iso(secs: int) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(secs, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def memory_age_days(modified_secs: int) -> int:
    return max(0, int(time()) - int(modified_secs)) // 86400


def memory_age(modified_secs: int) -> str:
    days = memory_age_days(modified_secs)
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def memory_freshness_text(modified_secs: int) -> str:
    days = memory_age_days(modified_secs)
    if days <= 1:
        return ""
    return (
        f"This memory is {days} days old. Memories are point-in-time observations, "
        "not live state — claims about code behavior or file:line citations may be "
        "outdated. Verify against current code before asserting as fact."
    )


def memory_freshness_note(modified_secs: int) -> str:
    text = memory_freshness_text(modified_secs)
    if not text:
        return ""
    return f"<system-reminder>{text}</system-reminder>\n"


def format_memory_manifest(memories: list[MemoryFileMeta]) -> str:
    lines: list[str] = []
    for meta in memories:
        prefix = f"[{meta.memory_type}] " if meta.memory_type else ""
        timestamp = format_unix_secs_iso(meta.modified_secs)
        if meta.description:
            lines.append(f"- {prefix}{meta.filename} ({timestamp}): {meta.description}")
        else:
            lines.append(f"- {prefix}{meta.filename}")
    return "\n".join(lines)


def truncate_entrypoint_content(raw: str) -> EntrypointTruncation:
    trimmed = raw.strip()
    lines = trimmed.splitlines()
    line_count = len(lines)
    byte_count = len(trimmed)
    was_line_truncated = line_count > MAX_ENTRYPOINT_LINES
    was_byte_truncated = byte_count > MAX_ENTRYPOINT_BYTES

    if not was_line_truncated and not was_byte_truncated:
        return EntrypointTruncation(
            content=trimmed,
            line_count=line_count,
            byte_count=byte_count,
            was_line_truncated=False,
            was_byte_truncated=False,
        )

    truncated = "\n".join(lines[:MAX_ENTRYPOINT_LINES]) if was_line_truncated else trimmed
    if len(truncated) > MAX_ENTRYPOINT_BYTES:
        cut_at = truncated[:MAX_ENTRYPOINT_BYTES].rfind("\n")
        truncated = truncated[: cut_at if cut_at != -1 else MAX_ENTRYPOINT_BYTES]

    if was_line_truncated and not was_byte_truncated:
        reason = f"{line_count} lines (limit: {MAX_ENTRYPOINT_LINES})"
    elif was_byte_truncated and not was_line_truncated:
        reason = (
            f"{byte_count} bytes (limit: {MAX_ENTRYPOINT_BYTES}) — "
            "index entries are too long"
        )
    else:
        reason = f"{line_count} lines and {byte_count} bytes"

    truncated += (
        f"\n\n> WARNING: {MEMORY_ENTRYPOINT} is {reason}. Only part of it was loaded. "
        "Keep index entries to one line under ~200 chars; move detail into topic files."
    )
    return EntrypointTruncation(
        content=truncated,
        line_count=line_count,
        byte_count=byte_count,
        was_line_truncated=was_line_truncated,
        was_byte_truncated=was_byte_truncated,
    )


def load_memory_index(dir_path: Path) -> EntrypointTruncation | None:
    index_path = dir_path / MEMORY_ENTRYPOINT
    if not index_path.exists():
        return None
    try:
        raw = index_path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not raw.strip():
        return None
    return truncate_entrypoint_content(raw)


def _single_line_hook(text: str) -> str:
    squashed = " ".join((text or "").split())
    if len(squashed) <= 180:
        return squashed
    return squashed[:177].rstrip() + "..."


def _rewrite_index(cwd: str) -> None:
    ensure_dir(cwd)
    metas = scan_memory_dir(memory_dir(cwd))
    lines = ["# MEMORY.md", "", "_auto-generated index of stored memories._", ""]
    for meta in metas:
        display_name = meta.name or Path(meta.filename).stem
        hook = meta.description or "(no description)"
        lines.append(f"- [{display_name}]({meta.filename}) — {_single_line_hook(hook)}")
    memory_index_file(cwd).write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_memory_prompt_content(dir_path: Path) -> str:
    parts: list[str] = []
    index = load_memory_index(dir_path)
    if index is not None:
        parts.append(f"## Memory Index (MEMORY.md)\n{index.content}")
    return "\n\n".join(parts).strip()


def build_context_block(cwd: str) -> str:
    return build_memory_prompt_content(memory_dir(cwd))
