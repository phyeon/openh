"""Session profile registry — specialized session types beyond the default."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from pathlib import Path


@dataclass
class ProfileSpec:
    id: str                          # "fnd", "default"
    display_name: str                # "Fruits & Dessert"
    wordmark: str                    # welcome screen text
    icon: str                        # sidebar icon emoji
    default_cwd: str | None = None   # auto-set CWD
    system_prompt_fn: Callable[[], str] | None = None
    extra_tools_fn: Callable[[], list] | None = None
    accent_color: str | None = None
    color_preset: str | None = None  # theme.COLOR_PRESETS key to apply on session
    placeholder: str = ""            # input placeholder override
    subtitle: str = ""               # welcome screen subtitle


_REGISTRY: dict[str, ProfileSpec] = {}
_LOADED = False


def register(spec: ProfileSpec) -> None:
    _REGISTRY[spec.id] = spec


def _auto_load() -> None:
    """Import all profile modules to trigger registration."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    try:
        from . import fnd  # noqa: F401
    except Exception:
        pass


def get_profile(profile_id: str) -> ProfileSpec | None:
    _auto_load()
    return _REGISTRY.get(profile_id)


def list_profiles() -> list[ProfileSpec]:
    _auto_load()
    return list(_REGISTRY.values())
