"""Memdir — persistent, file-based memory like Claude Code uses.

Layout (per-project, Claude Code compatible):

    ~/.claude/projects/<path-hash>/memory/
    ├── MEMORY.md                 # index (one-line pointer per memory)
    └── <name>.md                 # individual memory file with frontmatter

Each memory file has YAML-ish frontmatter:

    ---
    name: User role
    description: Short hook describing why this memory is useful
    type: user | feedback | project | reference
    ---

    {body}

The index MEMORY.md is a flat list the agent loads every session:

    - [Title](file.md) — one-line hook
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .cc_compat import memory_dir, memory_index_file

MemoryType = Literal["user", "feedback", "project", "reference"]

VALID_TYPES: tuple[MemoryType, ...] = ("user", "feedback", "project", "reference")


@dataclass
class Memory:
    name: str
    description: str
    type: MemoryType
    body: str
    path: Path | None = None


# ============================================================================
# Parsing / serialisation
# ============================================================================

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def parse_memory_file(path: Path) -> Memory | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        # No frontmatter: treat whole file as body, derive name from filename
        return Memory(
            name=path.stem,
            description="",
            type="reference",
            body=raw.strip(),
            path=path,
        )
    fm_raw, body = m.group(1), m.group(2)
    fields: dict[str, str] = {}
    for line in fm_raw.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            fields[key.strip().lower()] = val.strip()
    return Memory(
        name=fields.get("name", path.stem),
        description=fields.get("description", ""),
        type=_coerce_type(fields.get("type", "reference")),
        body=body.strip(),
        path=path,
    )


def _coerce_type(v: str) -> MemoryType:
    v = (v or "").strip().lower()
    if v in VALID_TYPES:
        return v  # type: ignore[return-value]
    return "reference"


def serialize_memory(mem: Memory) -> str:
    lines = [
        "---",
        f"name: {mem.name}",
        f"description: {mem.description}",
        f"type: {mem.type}",
        "---",
        "",
        mem.body.strip(),
        "",
    ]
    return "\n".join(lines)


def safe_filename(name: str) -> str:
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9가-힣_\- ]+", "", name)
    name = re.sub(r"\s+", "_", name)
    return (name or "untitled") + ".md"


# ============================================================================
# Directory operations
# ============================================================================

def ensure_dir(cwd: str) -> Path:
    d = memory_dir(cwd)
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_memories(cwd: str) -> list[Memory]:
    d = memory_dir(cwd)
    if not d.exists():
        return []
    out: list[Memory] = []
    for p in sorted(d.glob("*.md")):
        if p.name == "MEMORY.md":
            continue
        mem = parse_memory_file(p)
        if mem is not None:
            out.append(mem)
    return out


def save_memory(cwd: str, mem: Memory) -> Memory:
    d = ensure_dir(cwd)
    filename = safe_filename(mem.name)
    path = d / filename
    path.write_text(serialize_memory(mem), encoding="utf-8")
    mem.path = path
    # Update index
    _rewrite_index(cwd)
    return mem


def delete_memory(cwd: str, name: str) -> bool:
    d = memory_dir(cwd)
    if not d.exists():
        return False
    deleted = False
    for p in d.glob("*.md"):
        if p.name == "MEMORY.md":
            continue
        mem = parse_memory_file(p)
        if mem is not None and (mem.name.lower() == name.lower() or p.stem.lower() == name.lower()):
            try:
                p.unlink()
                deleted = True
            except OSError:
                pass
    if deleted:
        _rewrite_index(cwd)
    return deleted


def _rewrite_index(cwd: str) -> None:
    d = memory_dir(cwd)
    mems = list_memories(cwd)
    lines = ["# MEMORY.md", "", "_auto-generated index of stored memories._", ""]
    for mem in mems:
        filename = mem.path.name if mem.path else safe_filename(mem.name)
        hook = mem.description or "(no description)"
        lines.append(f"- [{mem.name}]({filename}) — {hook}")
    (d / "MEMORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ============================================================================
# Load memories into a system-context block
# ============================================================================

def build_context_block(cwd: str) -> str:
    """Return the full memory context to prepend to a turn."""
    mems = list_memories(cwd)
    if not mems:
        return ""

    parts = ["# Memory", ""]
    # Group by type for readability
    by_type: dict[str, list[Memory]] = {}
    for m in mems:
        by_type.setdefault(m.type, []).append(m)

    ORDER = ("user", "feedback", "project", "reference")
    for t in ORDER:
        if t not in by_type:
            continue
        parts.append(f"## {t}")
        parts.append("")
        for mem in by_type[t]:
            parts.append(f"### {mem.name}")
            if mem.description:
                parts.append(f"_{mem.description}_")
            parts.append("")
            parts.append(mem.body.strip())
            parts.append("")
    return "\n".join(parts).strip()
