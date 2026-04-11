"""Skills system — Claude Code-compatible skill loader.

A skill is a directory under ~/.claude/skills/<skill-name>/ containing:

    SKILL.md         — frontmatter + instructions markdown

Frontmatter:

    ---
    name: my-skill
    description: Short description shown when the model decides which skill to invoke
    ---

    {body — full skill instructions the model follows when invoked}

When a skill is invoked (via the Skill tool), its body becomes a system-like
message appended to the conversation, and the model continues with the
instructions in context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .cc_compat import SKILLS_DIR

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path


def list_skills() -> list[Skill]:
    if not SKILLS_DIR.exists():
        return []
    out: list[Skill] = []
    for entry in sorted(SKILLS_DIR.iterdir()):
        skill_md = _find_skill_file(entry)
        if skill_md is None:
            continue
        skill = _parse_skill(skill_md)
        if skill is not None:
            out.append(skill)
    return out


def get_skill(name: str) -> Skill | None:
    for s in list_skills():
        if s.name.lower() == name.lower():
            return s
    return None


def _find_skill_file(entry: Path) -> Path | None:
    if entry.is_file() and entry.suffix == ".md":
        return entry
    if entry.is_dir():
        skill_md = entry / "SKILL.md"
        if skill_md.exists():
            return skill_md
        skill_md = entry / f"{entry.name}.md"
        if skill_md.exists():
            return skill_md
    return None


def _parse_skill(path: Path) -> Skill | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(raw)
    if m:
        fm_raw, body = m.group(1), m.group(2)
        fields: dict[str, str] = {}
        for line in fm_raw.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                fields[key.strip().lower()] = val.strip()
        return Skill(
            name=fields.get("name", path.stem),
            description=fields.get("description", ""),
            body=body.strip(),
            path=path,
        )
    # No frontmatter: use filename
    return Skill(
        name=path.stem,
        description="",
        body=raw.strip(),
        path=path,
    )
