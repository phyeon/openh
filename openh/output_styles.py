"""Output style loader and resolver."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from .cc_compat import OPENH_DIR

PROJECT_OUTPUT_STYLES_DIRNAME = ".claurst/output-styles"
GLOBAL_OUTPUT_STYLES_DIR = OPENH_DIR / "output-styles"
_RUNTIME_STYLES: list["OutputStyleDef"] = []
_RUNTIME_STYLES_LOCK = Lock()
_PLUGIN_STYLE_SCAN_LOCK = Lock()
_PLUGIN_STYLE_CACHE: list["OutputStyleDef"] | None = None


@dataclass(frozen=True, slots=True)
class OutputStyleDef:
    name: str
    label: str
    description: str
    prompt: str


def builtin_styles() -> list[OutputStyleDef]:
    return [
        OutputStyleDef(
            name="default",
            label="Default",
            description="Standard Claurst responses.",
            prompt="",
        ),
        OutputStyleDef(
            name="concise",
            label="Concise",
            description="Short, direct responses with minimal explanation.",
            prompt=(
                "Be maximally concise. Skip preamble, summaries, and filler. "
                "Lead with the answer."
            ),
        ),
        OutputStyleDef(
            name="explanatory",
            label="Explanatory",
            description="Thorough explanations with reasoning and alternatives.",
            prompt=(
                "When explaining code or concepts, be thorough and educational. "
                "Include reasoning, alternatives considered, and potential pitfalls. "
                "Err on the side of over-explaining."
            ),
        ),
        OutputStyleDef(
            name="learning",
            label="Learning",
            description="Pedagogical mode - explains patterns and decisions.",
            prompt=(
                "This user is learning. Explain concepts as you implement them. "
                "Point out patterns, best practices, and why you made each decision. "
                "Use analogies when helpful."
            ),
        ),
    ]


def load_output_styles_dir(styles_dir: Path) -> list[OutputStyleDef]:
    if not styles_dir.exists():
        return []
    try:
        entries = list(styles_dir.iterdir())
    except OSError:
        return []

    styles: list[OutputStyleDef] = []
    for path in entries:
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".json"}:
            continue
        style = load_style_file(path)
        if style is not None:
            styles.append(style)
    styles.sort(key=lambda item: item.name)
    return styles


def load_style_file(path: Path) -> OutputStyleDef | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    stem = path.stem

    if path.suffix.lower() == ".json":
        try:
            data = json.loads(content)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return OutputStyleDef(
            name=str(data.get("name") or stem).strip() or stem,
            label=str(data.get("label") or stem).strip() or stem,
            description=str(data.get("description") or "").strip(),
            prompt=str(data.get("prompt") or "").strip(),
        )

    lines = content.splitlines()
    raw_label = lines[0].strip() if lines else stem
    label = raw_label.lstrip("#").strip() or stem
    description = lines[1].strip() if len(lines) >= 2 else ""
    prompt = "\n".join(lines[2:]).strip()
    return OutputStyleDef(
        name=stem,
        label=label,
        description=description,
        prompt=prompt,
    )


def _project_output_styles_dir(cwd: str | None) -> Path | None:
    root = str(cwd or "").strip()
    if not root:
        return None
    return Path(root) / PROJECT_OUTPUT_STYLES_DIRNAME


def all_styles(cwd: str | None = None) -> list[OutputStyleDef]:
    merged: dict[str, OutputStyleDef] = {style.name: style for style in builtin_styles()}
    for style in load_output_styles_dir(GLOBAL_OUTPUT_STYLES_DIR):
        merged[style.name] = style
    project_dir = _project_output_styles_dir(cwd)
    if project_dir is not None:
        for style in load_output_styles_dir(project_dir):
            merged[style.name] = style
    for style in runtime_styles():
        if style.name not in merged:
            merged[style.name] = style
    builtins = [style.name for style in builtin_styles()]
    ordered: list[OutputStyleDef] = []
    for name in builtins:
        if name in merged:
            ordered.append(merged.pop(name))
    ordered.extend(sorted(merged.values(), key=lambda item: item.name))
    return ordered


def find_style(name: str, cwd: str | None = None) -> OutputStyleDef | None:
    target = str(name or "").strip().lower()
    if not target:
        target = "default"
    for style in all_styles(cwd):
        if style.name.lower() == target:
            return style
    return None


def available_style_names(cwd: str | None = None) -> list[str]:
    return [style.name for style in all_styles(cwd)]


def resolve_style_prompt(name: str | None, cwd: str | None = None) -> str:
    style = find_style(name or "default", cwd)
    if style is None:
        return ""
    return style.prompt.strip()


def register_runtime_style(style: OutputStyleDef) -> None:
    with _RUNTIME_STYLES_LOCK:
        if any(existing.name == style.name for existing in _RUNTIME_STYLES):
            return
        _RUNTIME_STYLES.append(style)


def _plugin_search_roots() -> list[Path]:
    home = Path.home()
    roots = [
        home / ".codex" / ".tmp" / "plugins" / "plugins",
        home / ".codex" / "plugins",
    ]
    existing: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        resolved = root.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        existing.append(root)
    return existing


def _discover_plugin_output_style_dirs() -> list[Path]:
    dirs: list[Path] = []
    seen: set[Path] = set()
    for root in _plugin_search_roots():
        try:
            manifests = root.rglob("plugin.json")
        except OSError:
            continue
        for manifest in manifests:
            if manifest.parent.name != ".codex-plugin":
                continue
            plugin_dir = manifest.parent.parent
            styles_dir = plugin_dir / "output-styles"
            if not styles_dir.exists() or not styles_dir.is_dir():
                continue
            resolved = styles_dir.resolve(strict=False)
            if resolved in seen:
                continue
            seen.add(resolved)
            dirs.append(styles_dir)
    dirs.sort(key=lambda item: str(item))
    return dirs


def _plugin_runtime_styles() -> list[OutputStyleDef]:
    global _PLUGIN_STYLE_CACHE
    with _PLUGIN_STYLE_SCAN_LOCK:
        if _PLUGIN_STYLE_CACHE is not None:
            return list(_PLUGIN_STYLE_CACHE)

        styles: list[OutputStyleDef] = []
        seen_names: set[str] = set()
        for styles_dir in _discover_plugin_output_style_dirs():
            for style in load_output_styles_dir(styles_dir):
                if style.name in seen_names:
                    continue
                seen_names.add(style.name)
                styles.append(style)
        _PLUGIN_STYLE_CACHE = styles
        return list(styles)


def runtime_styles() -> list[OutputStyleDef]:
    with _RUNTIME_STYLES_LOCK:
        manual = list(_RUNTIME_STYLES)
    merged: list[OutputStyleDef] = []
    seen_names: set[str] = set()
    for style in manual + _plugin_runtime_styles():
        if style.name in seen_names:
            continue
        seen_names.add(style.name)
        merged.append(style)
    return merged
