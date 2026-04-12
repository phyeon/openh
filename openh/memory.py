"""AGENTS.md / CLAUDE.md hierarchical memory loading."""
from __future__ import annotations

from pathlib import Path


MAX_MEMORY_FILE_BYTES = 40 * 1024
MAX_INCLUDE_DEPTH = 10


def _strip_frontmatter(content: str) -> tuple[str, str]:
    if not content.startswith("---"):
        return "", content
    after_first = content[3:]
    end = after_first.find("\n---")
    if end == -1:
        return "", content
    frontmatter = after_first[:end].strip()
    body = after_first[end + 4 :].lstrip("\n")
    return frontmatter, body


def _resolve_include_path(path_str: str, base_dir: Path) -> Path:
    if path_str.startswith("~/"):
        return Path.home() / path_str[2:]
    if path_str.startswith("~"):
        return Path.home() / path_str[1:]
    include_path = Path(path_str)
    if include_path.is_absolute():
        return include_path
    return base_dir / include_path


def _expand_includes(
    content: str,
    base_dir: Path,
    visited: set[Path],
    depth: int = 0,
) -> str:
    if depth >= MAX_INCLUDE_DEPTH:
        return content

    expanded_lines: list[str] = []
    for line in content.splitlines():
        trimmed = line.strip()
        if not trimmed.startswith("@include "):
            expanded_lines.append(line)
            continue

        include_raw = trimmed[len("@include ") :].strip()
        include_path = _resolve_include_path(include_raw, base_dir)
        canonical = include_path.resolve(strict=False)

        if canonical in visited:
            expanded_lines.append(f"<!-- circular @include {include_raw} skipped -->")
            continue
        if not include_path.exists() or not include_path.is_file():
            expanded_lines.append(f"<!-- @include {include_raw} not found -->")
            continue
        try:
            if include_path.stat().st_size > MAX_MEMORY_FILE_BYTES:
                expanded_lines.append(
                    f"<!-- @include {include_raw} exceeds 40KB limit -->"
                )
                continue
            raw = include_path.read_text(encoding="utf-8")
        except OSError:
            expanded_lines.append(f"<!-- @include {include_raw} not found -->")
            continue

        nested_visited = set(visited)
        nested_visited.add(canonical)
        expanded_lines.append(
            _expand_includes(
                raw,
                include_path.parent or base_dir,
                nested_visited,
                depth + 1,
            ).rstrip()
        )

    return "\n".join(expanded_lines).strip()


def _load_memory_file(path: Path) -> str:
    try:
        meta = path.stat()
    except OSError:
        return ""
    if meta.st_size > MAX_MEMORY_FILE_BYTES:
        return ""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    _, body = _strip_frontmatter(raw)
    visited = {path.resolve(strict=False)}
    return _expand_includes(body, path.parent, visited).strip()


def _load_scope_files(base_dir: Path) -> list[str]:
    loaded: list[str] = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        path = base_dir / name
        if not path.exists() or not path.is_file():
            continue
        content = _load_memory_file(path)
        if content:
            loaded.append(content)
    return loaded


def load_memory(cwd: str) -> str:
    """Return hierarchical memory text in public-style scope order."""
    project_root = Path(cwd).resolve()
    parts: list[str] = []

    rules_dir = Path.home() / ".claurst" / "rules"
    if rules_dir.exists():
        try:
            managed_files = sorted(
                p for p in rules_dir.iterdir() if p.is_file() and p.suffix == ".md"
            )
        except OSError:
            managed_files = []
        for path in managed_files:
            content = _load_memory_file(path)
            if content:
                parts.append(content)

    parts.extend(_load_scope_files(Path.home() / ".claurst"))
    parts.extend(_load_scope_files(project_root))
    parts.extend(_load_scope_files(project_root / ".claurst"))

    return "\n\n".join(part for part in parts if part.strip()).strip()


def build_system_context(cwd: str, date_str: str) -> str:
    """Build a synthetic first-turn context message for the agent."""
    lines = [
        "<environment>",
        f"Working directory: {cwd}",
        f"Date: {date_str}",
    ]
    try:
        import subprocess

        branch = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
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

    try:
        from . import memdir

        memdir_block = memdir.build_context_block(cwd)
        if memdir_block:
            lines.append("")
            lines.append(memdir_block)
    except Exception:
        pass

    return "\n".join(lines)
