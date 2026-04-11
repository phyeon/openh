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


# ============================================================================
# Font presets
# ============================================================================

FONT_PRESETS = {
    "System (Sans)": ("-apple-system", "SFMono-Regular"),
    "Inter": ("Inter", "JetBrains Mono"),
    "Serif (Georgia)": ("Georgia", "Courier New"),
}

# Active fonts — defaults
FONT_SANS = "-apple-system"
FONT_MONO = "SFMono-Regular"


def set_font(preset_name: str) -> None:
    global FONT_SANS, FONT_MONO
    if preset_name in FONT_PRESETS:
        FONT_SANS, FONT_MONO = FONT_PRESETS[preset_name]


# ============================================================================
# Color theme presets (dark + light pairs)
# ============================================================================

COLOR_PRESETS: dict[str, tuple[Tokens, Tokens]] = {}


def _register_preset(name: str, dark: Tokens, light: Tokens) -> None:
    COLOR_PRESETS[name] = (dark, light)


def _dark(accent: str, accent_dk: str, accent_hv: str, accent_pr: str,
          bg: str = "#121212", surface: str = "#1e1e1e", elevated: str = "#2a2a2e",
          hover: str = "#313136", sidebar: str = "#e0141416",
          text1: str = "#e2e8f0", text2: str = "#a0aec0", text3: str = "#64748b",
          text_dis: str = "#475569", accent_faint: str = "#1a2030") -> Tokens:
    return Tokens(
        BG_SIDEBAR=sidebar, BG_DEEPEST=bg, BG_PAGE=surface, BG_ELEVATED=elevated,
        BG_HOVER=hover, BG_SIDEBAR_SELECTED="#1c1c22", BG_STATUS=bg,
        TEXT_PRIMARY=text1, TEXT_SECONDARY=text2, TEXT_TERTIARY=text3,
        TEXT_DISABLED=text_dis, TEXT_ON_ACCENT="#ffffff",
        ACCENT=accent, ACCENT_DARK=accent_dk, ACCENT_HOVER=accent_hv,
        ACCENT_PRESSED=accent_pr, ACCENT_FAINT=accent_faint,
        BORDER_FAINT="#1f2028", BORDER_SUBTLE="#2a2e38", BORDER_STRONG="#3a3e48",
        ERROR="#ef4444", WARN="#f59e0b", SUCCESS="#22c55e",
        TOOL_CALL_BG="#161a24", TOOL_CALL_BORDER="#222840",
        TOOL_RESULT_BG="#141820", TOOL_RESULT_BORDER="#1e2430",
        ERROR_BG="#2a1010",
    )


def _light(accent: str, accent_dk: str, accent_hv: str, accent_pr: str,
           bg: str = "#f8fafc", surface: str = "#f1f5f9", elevated: str = "#ffffff",
           hover: str = "#e2e8f0", sidebar: str = "#e8f1f5f9",
           text1: str = "#0f172a", text2: str = "#475569", text3: str = "#94a3b8",
           text_dis: str = "#cbd5e1", accent_faint: str = "#dbeafe") -> Tokens:
    return Tokens(
        BG_PAGE=bg, BG_SIDEBAR=sidebar, BG_DEEPEST=surface, BG_ELEVATED=elevated,
        BG_HOVER=hover, BG_SIDEBAR_SELECTED="#dde4ee", BG_STATUS=surface,
        TEXT_PRIMARY=text1, TEXT_SECONDARY=text2, TEXT_TERTIARY=text3,
        TEXT_DISABLED=text_dis, TEXT_ON_ACCENT="#ffffff",
        ACCENT=accent, ACCENT_DARK=accent_dk, ACCENT_HOVER=accent_hv,
        ACCENT_PRESSED=accent_pr, ACCENT_FAINT=accent_faint,
        BORDER_FAINT="#e2e8f0", BORDER_SUBTLE="#cbd5e1", BORDER_STRONG="#94a3b8",
        ERROR="#dc2626", WARN="#d97706", SUCCESS="#16a34a",
        TOOL_CALL_BG="#eef2ff", TOOL_CALL_BORDER="#c7d2fe",
        TOOL_RESULT_BG="#f0f4f8", TOOL_RESULT_BORDER="#c8d4e0",
        ERROR_BG="#fef2f2",
    )


# --- Register 10 production-grade palettes ---

# 1. Default (Tailwind Blue)
_register_preset("Blue", DARK, LIGHT)

# 2. Charcoal (VS Code-inspired neutral)
_register_preset("Charcoal",
    _dark("#3b82f6", "#2563eb", "#60a5fa", "#1d4ed8", bg="#0a0a0a", surface="#171717", elevated="#262626", hover="#2e2e2e", sidebar="#e00e0e10"),
    _light("#2563eb", "#1d4ed8", "#3b82f6", "#1e40af", bg="#fafafa", surface="#f5f5f5"),
)

# 3. Mocha (Catppuccin-inspired warm brown)
_register_preset("Mocha",
    _dark("#cba6f7", "#b4befe", "#d4b8ff", "#a78bfa",
          bg="#1e1e2e", surface="#24243a", elevated="#313244", hover="#3a3a4e", sidebar="#e018182c",
          text1="#cdd6f4", text2="#a6adc8", text3="#7f849c", accent_faint="#2a2040"),
    _light("#8b5cf6", "#7c3aed", "#a78bfa", "#6d28d9",
           bg="#eff1f5", surface="#e6e9ef", accent_faint="#ede9fe"),
)

# 4. Nord (arctic, cool blue-gray)
_register_preset("Nord",
    _dark("#88c0d0", "#81a1c1", "#8fbcbb", "#5e81ac",
          bg="#2e3440", surface="#3b4252", elevated="#434c5e", hover="#4c566a", sidebar="#e02c3240",
          text1="#eceff4", text2="#d8dee9", text3="#81a1c1", accent_faint="#2e3848"),
    _light("#5e81ac", "#4c6a96", "#81a1c1", "#3b5a80",
           bg="#eceff4", surface="#e5e9f0", accent_faint="#dce4f0"),
)

# 5. Forest (earthy green)
_register_preset("Forest",
    _dark("#4ade80", "#22c55e", "#86efac", "#16a34a",
          bg="#0c1210", surface="#141e1a", elevated="#1c2a24", hover="#243430", sidebar="#e00c1410",
          text1="#dcfce7", text2="#a7c4b0", text3="#5e8a70", accent_faint="#0c2818"),
    _light("#16a34a", "#15803d", "#22c55e", "#166534",
           bg="#f0fdf4", surface="#ecfce5", accent_faint="#d1fae5"),
)

# 6. Sunset (warm coral/orange)
_register_preset("Sunset",
    _dark("#fb923c", "#f97316", "#fdba74", "#ea580c",
          bg="#18120e", surface="#201810", elevated="#2c2018", hover="#362820", sidebar="#e016100c",
          text1="#fff7ed", text2="#c4a888", text3="#8a7060", accent_faint="#2c1808"),
    _light("#ea580c", "#c2410c", "#f97316", "#9a3412",
           bg="#fffbf5", surface="#fff7ed", accent_faint="#ffedd5"),
)

# 7. Rose (soft pink)
_register_preset("Rose",
    _dark("#fb7185", "#f43f5e", "#fda4af", "#e11d48",
          bg="#18100e", surface="#201416", elevated="#2c1c20", hover="#362428", sidebar="#e016100e",
          text1="#fff1f2", text2="#c4a0a8", text3="#8a6068", accent_faint="#2c0c14"),
    _light("#e11d48", "#be123c", "#f43f5e", "#9f1239",
           bg="#fff5f5", surface="#fff1f2", accent_faint="#ffe4e6"),
)

# 8. Midnight (deep navy, cyan accent)
_register_preset("Midnight",
    _dark("#22d3ee", "#06b6d4", "#67e8f9", "#0891b2",
          bg="#020617", surface="#0f172a", elevated="#1e293b", hover="#253348", sidebar="#e0040814",
          text1="#f1f5f9", text2="#94a3b8", text3="#64748b", accent_faint="#082030"),
    _light("#0891b2", "#0e7490", "#06b6d4", "#155e75",
           bg="#f0f9ff", surface="#e0f2fe", accent_faint="#cffafe"),
)

# 9. Lavender (soft purple)
_register_preset("Lavender",
    _dark("#a78bfa", "#8b5cf6", "#c4b5fd", "#7c3aed",
          bg="#110e1a", surface="#1a1526", elevated="#252030", hover="#302a3a", sidebar="#e00e0c18",
          text1="#f5f3ff", text2="#b0a0c0", text3="#786890", accent_faint="#1c1430"),
    _light("#7c3aed", "#6d28d9", "#8b5cf6", "#5b21b6",
           bg="#faf5ff", surface="#f5f3ff", accent_faint="#ede9fe"),
)

# 10. Slate (minimal grayscale)
_register_preset("Slate",
    _dark("#94a3b8", "#78889c", "#b0bcc8", "#64748b",
          bg="#0f1115", surface="#1a1c22", elevated="#24262e", hover="#2c2e36", sidebar="#e00e1014",
          text1="#e2e8f0", text2="#94a3b8", text3="#64748b", accent_faint="#1a1e28"),
    _light("#64748b", "#475569", "#94a3b8", "#334155",
           bg="#f8fafc", surface="#f1f5f9", accent_faint="#e2e8f0"),
)


def set_color_preset(name: str) -> None:
    """Apply a named color preset. Respects current light/dark mode."""
    global _current, DARK, LIGHT
    if name not in COLOR_PRESETS:
        return
    dark, light = COLOR_PRESETS[name]
    DARK = dark
    LIGHT = light
    _current = DARK if _current_mode == "dark" else LIGHT
    _sync_module_vars()


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
