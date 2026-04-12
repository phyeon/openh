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
_NAME_META_RE = re.compile(r"^<!--\s*prompt-name:\s*(.*?)\s*-->\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Preset:
    slug: str
    name: str
    text: str
    is_builtin: bool
    path: Path | None


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


def _decode_preset_document(path: Path, content: str) -> Preset:
    lines = content.splitlines()
    display_name = path.stem
    body = content
    if lines:
        match = _NAME_META_RE.match(lines[0].strip())
        if match:
            parsed_name = match.group(1).strip()
            if parsed_name:
                display_name = parsed_name
            body = "\n".join(lines[1:]).lstrip("\n")
    return Preset(
        slug=path.stem,
        name=display_name,
        text=body,
        is_builtin=False,
        path=path,
    )


def _encode_preset_document(name: str, text: str) -> str:
    body = str(text or "")
    return f"<!-- prompt-name: {name.strip()} -->\n\n{body}"


def builtin() -> Preset:
    return Preset(
        slug=BUILTIN_NAME,
        name=BUILTIN_NAME,
        text=SYSTEM_PROMPT,
        is_builtin=True,
        path=None,
    )


def list_presets() -> list[Preset]:
    ensure_dir()
    presets: list[Preset] = [builtin()]
    for path in sorted(PROMPTS_DIR.glob("*.md"), key=lambda item: item.name):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if path.stem.lower() == BUILTIN_NAME:
            continue
        presets.append(_decode_preset_document(path, text))
    return presets


def get_preset(name: str) -> Preset | None:
    target = str(name or "").strip()
    if not target:
        return builtin()
    lowered = target.lower()
    safe = _safe_filename(target)
    if lowered == BUILTIN_NAME or safe == BUILTIN_NAME:
        return builtin()
    for preset in list_presets():
        if preset.is_builtin:
            continue
        if preset.slug.lower() == lowered:
            return preset
        if preset.name.lower() == lowered:
            return preset
        if preset.slug.lower() == safe:
            return preset
    return None


def save_preset(name: str, text: str) -> Preset:
    """Create or overwrite a named preset. Cannot target the built-in."""
    clean_name = name.strip()
    if clean_name.lower() == BUILTIN_NAME:
        raise ValueError("cannot overwrite the built-in 'default' preset")
    if not clean_name:
        raise ValueError("preset name is required")
    ensure_dir()
    existing = get_preset(clean_name)
    path = existing.path if existing and existing.path is not None else _path_for(clean_name)
    path.write_text(_encode_preset_document(clean_name, text), encoding="utf-8")
    return Preset(
        slug=path.stem,
        name=clean_name,
        text=text,
        is_builtin=False,
        path=path,
    )


def delete_preset(name: str) -> None:
    target = get_preset(name)
    if target and target.is_builtin:
        raise ValueError("cannot delete the built-in 'default' preset")
    path = target.path if target and target.path is not None else _path_for(name)
    if path.exists():
        path.unlink()


def resolve_active(active_name: str | None) -> str:
    """Return the effective prompt text for the given active preset name."""
    if not active_name:
        return SYSTEM_PROMPT
    preset = get_preset(active_name)
    if preset is None:
        return SYSTEM_PROMPT
    return preset.text or SYSTEM_PROMPT
