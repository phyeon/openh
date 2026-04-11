"""Design tokens with light/dark mode.

Tokens are runtime-mutable module-level variables. Call `set_mode('light')`
or `set_mode('dark')` to switch; then re-render any widgets that reference
the module. Hex values are sampled from Claude.app's CSS variables.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Mode = Literal["dark", "light"]


@dataclass(frozen=True)
class Tokens:
    # Backgrounds (darkest → lightest)
    BG_SIDEBAR: str
    BG_DEEPEST: str
    BG_PAGE: str
    BG_ELEVATED: str
    BG_HOVER: str
    BG_SIDEBAR_SELECTED: str
    BG_STATUS: str

    # Text
    TEXT_PRIMARY: str
    TEXT_SECONDARY: str
    TEXT_TERTIARY: str
    TEXT_DISABLED: str
    TEXT_ON_ACCENT: str

    # Accent
    ACCENT: str
    ACCENT_DARK: str
    ACCENT_HOVER: str
    ACCENT_PRESSED: str
    ACCENT_FAINT: str

    # Borders
    BORDER_FAINT: str
    BORDER_SUBTLE: str
    BORDER_STRONG: str

    # Status
    ERROR: str
    WARN: str
    SUCCESS: str

    # Tool tints
    TOOL_CALL_BG: str
    TOOL_CALL_BORDER: str
    TOOL_RESULT_BG: str
    TOOL_RESULT_BORDER: str

    # Error panel background
    ERROR_BG: str


# ---------- Dark mode tokens ----------
# Refined dark palette with Pantone-inspired muted blue accent.
# Backgrounds are cool-neutral (no warm/yellow cast), text is soft white.
_DARK_ACCENT = "#5B8DEF"
DARK = Tokens(
    BG_SIDEBAR="#e0161719",   # semi-transparent (alpha 0xe0)
    BG_DEEPEST="#111214",
    BG_PAGE="#1a1b1e",
    BG_ELEVATED="#232529",
    BG_HOVER="#282a2f",
    BG_SIDEBAR_SELECTED="#1f2126",
    BG_STATUS="#111214",
    TEXT_PRIMARY="#E8EAED",
    TEXT_SECONDARY="#A0A4AB",
    TEXT_TERTIARY="#6B7079",
    TEXT_DISABLED="#4a4e56",
    TEXT_ON_ACCENT="#ffffff",
    ACCENT=_DARK_ACCENT,
    ACCENT_DARK="#4A7AD8",
    ACCENT_HOVER="#7BA5F5",
    ACCENT_PRESSED="#4670C8",
    ACCENT_FAINT="#1c2436",
    BORDER_FAINT="#232529",
    BORDER_SUBTLE="#2e3138",
    BORDER_STRONG="#3d4148",
    ERROR="#EF6461",
    WARN="#E8A555",
    SUCCESS="#6BCB77",
    TOOL_CALL_BG="#1c2028",
    TOOL_CALL_BORDER="#2a3344",
    TOOL_RESULT_BG="#1a1e24",
    TOOL_RESULT_BORDER="#252c38",
    ERROR_BG="#2c1a1a",
)

# ---------- Light mode tokens ----------
# Clean cool-white with soft blue accent.
LIGHT = Tokens(
    BG_PAGE="#fafbfc",
    BG_SIDEBAR="#e8f2f3f5",   # semi-transparent
    BG_DEEPEST="#ebedf0",
    BG_ELEVATED="#ffffff",
    BG_HOVER="#e8eaed",
    BG_SIDEBAR_SELECTED="#e1e4e8",
    BG_STATUS="#ebedf0",
    TEXT_PRIMARY="#1a1c20",
    TEXT_SECONDARY="#444952",
    TEXT_TERTIARY="#6b7280",
    TEXT_DISABLED="#a0a5ae",
    TEXT_ON_ACCENT="#ffffff",
    ACCENT="#4878DB",
    ACCENT_DARK="#3660B8",
    ACCENT_HOVER="#5E8CE6",
    ACCENT_PRESSED="#3358A8",
    ACCENT_FAINT="#dfe8f8",
    BORDER_FAINT="#e2e5ea",
    BORDER_SUBTLE="#d0d4db",
    BORDER_STRONG="#a0a6b0",
    ERROR="#d03838",
    WARN="#c07a1c",
    SUCCESS="#3aa169",
    TOOL_CALL_BG="#edf1fa",
    TOOL_CALL_BORDER="#c4d0e8",
    TOOL_RESULT_BG="#eef2f7",
    TOOL_RESULT_BORDER="#c8d1de",
    ERROR_BG="#fde8e8",
)


# Current mode state
_current_mode: Mode = "dark"
_current: Tokens = DARK


def set_mode(mode: Mode) -> None:
    global _current_mode, _current
    _current_mode = mode
    _current = DARK if mode == "dark" else LIGHT
    _sync_module_vars()


def current_mode() -> Mode:
    return _current_mode


def is_dark() -> bool:
    return _current_mode == "dark"


# ============================================================================
# Proxy module-level names so legacy `theme.BG_PAGE` access still works.
# These are reassigned by _sync_module_vars() whenever the mode changes.
# ============================================================================

def _sync_module_vars() -> None:
    import sys
    mod = sys.modules[__name__]
    for field in Tokens.__dataclass_fields__:
        setattr(mod, field, getattr(_current, field))


# Static constants that don't change with theme
FONT_SANS = "-apple-system"
FONT_MONO = "SFMono-Regular"

RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 16
RADIUS_PILL = 999

SIDEBAR_WIDTH = 280
SIDEBAR_COLLAPSED_WIDTH = 0

MESSAGE_MAX_WIDTH = 760
PADDING_GUTTER = 24
TOP_BAR_HEIGHT = 52
STATUS_BAR_HEIGHT = 28

TOOL_DESCRIPTIONS = {
    "Read": "Read a file from disk",
    "Write": "Create or overwrite a file",
    "Edit": "Modify an existing file",
    "Bash": "Execute a shell command",
    "Glob": "Find files by pattern",
    "Grep": "Search file contents",
}

# Initialize module-level vars on import
_sync_module_vars()
