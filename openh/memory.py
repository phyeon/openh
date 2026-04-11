"""CLAUDE.md memory loader.

When a session starts in a workspace, collect all CLAUDE.md / AGENTS.md files
from the cwd walking UP to the home directory, and concatenate them as
instruction context to inject into the conversation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable


MEMORY_FILENAMES = ("CLAUDE.md", "AGENTS.md", ".claude/CLAUDE.md")


def _walk_up(start: Path) -> Iterable[Path]:
    p = start.resolve()
    home = Path.home().resolve()
    yielded = set()
    while True:
        if p in yielded:
            break
        yielded.add(p)
        yield p
        if p == home or p == p.parent:
            break
        p = p.parent


def load_memory(cwd: str) -> str:
    """Return a single concatenated memory block, newest (nearest) first."""
    results: list[tuple[Path, str]] = []
    for dirpath in _walk_up(Path(cwd)):
        for name in MEMORY_FILENAMES:
            candidate = dirpath / name
            if candidate.exists() and candidate.is_file():
                try:
                    text = candidate.read_text(encoding="utf-8")
                except OSError:
                    continue
                results.append((candidate, text.strip()))

    if not results:
        return ""

    parts: list[str] = []
    for path, text in results:
        if not text:
            continue
        parts.append(f"### {path}\n\n{text}")
    if not parts:
        return ""

    header = "# Project memory\n\nThe following files contain project-specific instructions and context:\n\n"
    return header + "\n\n---\n\n".join(parts)


def build_system_context(cwd: str, date_str: str) -> str:
    """Build a synthetic first-turn context message for the agent."""
    lines = [
        "<environment>",
        f"Working directory: {cwd}",
        f"Date: {date_str}",
    ]
    # git info if available
    try:
        import subprocess
        branch = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if branch.returncode == 0:
            lines.append(f"Git branch: {branch.stdout.strip()}")
    except Exception:
        pass
    lines.append("</environment>")

    memory = load_memory(cwd)
    if memory:
        lines.append("")
        lines.append(memory)

    # Memdir memories (Claude Code compatible)
    try:
        from . import memdir
        memdir_block = memdir.build_context_block(cwd)
        if memdir_block:
            lines.append("")
            lines.append(memdir_block)
    except Exception:
        pass

    return "\n".join(lines)
