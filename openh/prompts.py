"""System prompt presets.

A preset is a named system prompt. There is exactly one built-in preset
("default") which cannot be deleted or overwritten. Users can create any
number of named presets, which are saved as markdown files under
~/.openh/prompts/.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import SYSTEM_PROMPT

PROMPTS_DIR = Path.home() / ".openh" / "prompts"

BUILTIN_NAME = "default"


@dataclass(frozen=True)
class Preset:
    name: str
    text: str
    is_builtin: bool
    path: Path | None  # None for the built-in


def ensure_dir() -> None:
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_filename(name: str) -> str:
    """Convert a human name into a safe filename stem."""
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9가-힣_\- ]+", "", name)
    name = re.sub(r"\s+", "-", name)
    return name or "untitled"


def _path_for(name: str) -> Path:
    return PROMPTS_DIR / f"{_safe_filename(name)}.md"


def builtin() -> Preset:
    return Preset(
        name=BUILTIN_NAME,
        text=SYSTEM_PROMPT,
        is_builtin=True,
        path=None,
    )


def list_presets() -> list[Preset]:
    ensure_dir()
    presets: list[Preset] = [builtin()]
    for p in sorted(PROMPTS_DIR.glob("*.md"), key=lambda x: x.name):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        stem = p.stem
        if stem.lower() == BUILTIN_NAME:
            # Name collision — skip so we don't shadow the built-in
            continue
        presets.append(Preset(name=stem, text=text, is_builtin=False, path=p))
    return presets


def get_preset(name: str) -> Preset | None:
    if name == BUILTIN_NAME:
        return builtin()
    for p in list_presets():
        if p.name.lower() == name.lower():
            return p
    return None


def save_preset(name: str, text: str) -> Preset:
    """Create or overwrite a named preset. Cannot target the built-in."""
    if name.strip().lower() == BUILTIN_NAME:
        raise ValueError("cannot overwrite the built-in 'default' preset")
    if not name.strip():
        raise ValueError("preset name is required")
    ensure_dir()
    path = _path_for(name)
    path.write_text(text, encoding="utf-8")
    return Preset(name=path.stem, text=text, is_builtin=False, path=path)


def delete_preset(name: str) -> None:
    if name.strip().lower() == BUILTIN_NAME:
        raise ValueError("cannot delete the built-in 'default' preset")
    path = _path_for(name)
    if path.exists():
        path.unlink()


def resolve_active(active_name: str | None) -> str:
    """Return the effective prompt text for the given active preset name."""
    if not active_name or active_name.lower() == BUILTIN_NAME:
        return SYSTEM_PROMPT
    preset = get_preset(active_name)
    if preset is None:
        return SYSTEM_PROMPT
    return preset.text or SYSTEM_PROMPT
