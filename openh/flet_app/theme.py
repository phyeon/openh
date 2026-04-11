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
# Extracted from Claude.app CSS variables (2025-10-17)
# --bg-000: hsl(60 2.1% 18.4%) = #2f2f2d
# --accent-brand: #d97757 (clay)
DARK = Tokens(
    BG_SIDEBAR="#e0252523",   # --bg-100 with alpha
    BG_DEEPEST="#131312",     # --bg-300
    BG_PAGE="#2f2f2d",        # --bg-000
    BG_ELEVATED="#3a3a37",    # elevated surface
    BG_HOVER="#44443f",       # hover
    BG_SIDEBAR_SELECTED="#33332f",
    BG_STATUS="#1f1e1d",      # --bg-200
    TEXT_PRIMARY="#d9d9d9",
    TEXT_SECONDARY="#999999",
    TEXT_TERTIARY="#6e6e6e",
    TEXT_DISABLED="#484848",
    TEXT_ON_ACCENT="#d9d9d9",
    ACCENT="#d97757",         # --claude-accent-clay
    ACCENT_DARK="#c4633f",
    ACCENT_HOVER="#e8926e",
    ACCENT_PRESSED="#b85a38",
    ACCENT_FAINT="#3a2820",
    BORDER_FAINT="#3a3936",   # --border subtle
    BORDER_SUBTLE="#4a4944",
    BORDER_STRONG="#5a5952",
    ERROR="#e85d5d",          # --danger
    WARN="#e8a555",
    SUCCESS="#6bcb77",        # --success
    TOOL_CALL_BG="#2a2825",
    TOOL_CALL_BORDER="#4a4538",
    TOOL_RESULT_BG="#252422",
    TOOL_RESULT_BORDER="#3a3832",
    ERROR_BG="#3a1f1f",
)

# ---------- Light mode tokens ----------
# Extracted from Claude.app CSS variables (2025-10-17)
# --bg-000: hsl(0 0% 100%) = #ffffff
# --bg-100: hsl(48 33.3% 97.1%) = #faf9f5
LIGHT = Tokens(
    BG_PAGE="#ffffff",         # --bg-000
    BG_SIDEBAR="#e8faf9f5",   # --bg-100 with alpha
    BG_DEEPEST="#f0eee6",     # --bg-300
    BG_ELEVATED="#ffffff",
    BG_HOVER="#f4f4ec",       # --bg-200
    BG_SIDEBAR_SELECTED="#ece9df",
    BG_STATUS="#f0eee6",
    TEXT_PRIMARY="#131312",    # --text-000
    TEXT_SECONDARY="#3c3c39",  # --text-200
    TEXT_TERTIARY="#72716b",   # --text-400
    TEXT_DISABLED="#a6a39a",   # --text-500
    TEXT_ON_ACCENT="#ffffff",
    ACCENT="#d97757",         # --claude-accent-clay
    ACCENT_DARK="#c4633f",
    ACCENT_HOVER="#e8926e",
    ACCENT_PRESSED="#b85a38",
    ACCENT_FAINT="#fae8df",
    BORDER_FAINT="#e5e3da",
    BORDER_SUBTLE="#d5d3c8",
    BORDER_STRONG="#a6a39a",
    ERROR="#d03838",          # --danger
    WARN="#c07a1c",
    SUCCESS="#3aa169",
    TOOL_CALL_BG="#f8f5ec",
    TOOL_CALL_BORDER="#e0d8c4",
    TOOL_RESULT_BG="#f4f4f0",
    TOOL_RESULT_BORDER="#d8d6cc",
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
    "System (Sans)": {
        "sans": "Pretendard",
        "sans_fallback": ["Apple SD Gothic Neo", "-apple-system", "Arial Unicode MS"],
        "mono": "Menlo",
        "mono_fallback": ["SFMono-Regular", "Monaco"],
        "em": "Noto Serif KR",
        "em_fallback": ["New York", "Times New Roman", "Apple SD Gothic Neo"],
    },
    "Avenir Next": {
        "sans": "Avenir Next",
        "sans_fallback": ["Pretendard", "Apple SD Gothic Neo", "-apple-system"],
        "mono": "Menlo",
        "mono_fallback": ["SFMono-Regular", "Monaco"],
        "em": "Noto Serif KR",
        "em_fallback": ["New York", "Times New Roman", "Apple SD Gothic Neo"],
    },
    "Inter": {
        "sans": "Pretendard",
        "sans_fallback": ["Avenir Next", "Apple SD Gothic Neo", "-apple-system"],
        "mono": "Menlo",
        "mono_fallback": ["SFMono-Regular", "Monaco"],
        "em": "Noto Serif KR",
        "em_fallback": ["New York", "Times New Roman", "Apple SD Gothic Neo"],
    },
    "Serif (Reading)": {
        "sans": "Noto Serif KR",
        "sans_fallback": ["Pretendard", "Apple SD Gothic Neo", "Times New Roman"],
        "mono": "Menlo",
        "mono_fallback": ["SFMono-Regular", "Monaco"],
        "em": "Noto Serif KR",
        "em_fallback": ["New York", "Times New Roman", "Apple SD Gothic Neo"],
    },
    "Serif (Georgia)": {
        "sans": "Noto Serif KR",
        "sans_fallback": ["Pretendard", "Apple SD Gothic Neo", "Times New Roman"],
        "mono": "Menlo",
        "mono_fallback": ["SFMono-Regular", "Monaco"],
        "em": "Noto Serif KR",
        "em_fallback": ["New York", "Times New Roman", "Apple SD Gothic Neo"],
    },
}

# Active fonts — defaults
FONT_SANS = "Pretendard"
FONT_SANS_FALLBACK = ["Apple SD Gothic Neo", "-apple-system", "Arial Unicode MS"]
FONT_MONO = "Menlo"
FONT_MONO_FALLBACK = ["SFMono-Regular", "Monaco"]
FONT_EM = "Noto Serif KR"
FONT_EM_FALLBACK = ["New York", "Times New Roman", "Apple SD Gothic Neo"]
FONT_SIZE = 16  # base chat font size


def set_font_size(size: int) -> None:
    global FONT_SIZE
    FONT_SIZE = max(12, min(24, size))


def set_font(preset_name: str) -> None:
    global FONT_SANS, FONT_SANS_FALLBACK, FONT_MONO, FONT_MONO_FALLBACK, FONT_EM, FONT_EM_FALLBACK
    if preset_name in FONT_PRESETS:
        preset = FONT_PRESETS[preset_name]
        FONT_SANS = preset["sans"]
        FONT_SANS_FALLBACK = list(preset["sans_fallback"])
        FONT_MONO = preset["mono"]
        FONT_MONO_FALLBACK = list(preset["mono_fallback"])
        FONT_EM = preset["em"]
        FONT_EM_FALLBACK = list(preset["em_fallback"])


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

# 1. Claude (official Claude.app colors)
_register_preset("Claude", DARK, LIGHT)

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

# 11. Fruits & Dessert
# Light: 상큼 과즙 — 딸기 핑크 + 민트 + 피치 화이트. 밝고 발랄.
# Dark: 금박 엘레강스 — 딥 다크 초콜릿에 골드 액센트. 고급 디저트 부티크.
_register_preset("Fruits & Dessert",
    _dark(
        accent="#d4a857",       # antique gold
        accent_dk="#b8923e",    # deep gold
        accent_hv="#e4c47a",    # champagne gold hover
        accent_pr="#9a7a2c",    # burnished gold press
        bg="#0e0c08",           # almost black with warmth
        surface="#1a1610",      # dark chocolate
        elevated="#262014",     # rich dark truffle
        hover="#302a1e",        # cocoa hover
        sidebar="#e01a1610",    # deep dark sidebar
        text1="#f4e8d0",        # warm champagne
        text2="#b8a888",        # muted gold
        text3="#7a6e58",        # aged bronze
        text_dis="#4a4030",     # dark khaki
        accent_faint="#1e1a0e", # dark gold tint
    ),
    _light(
        accent="#e05880",       # strawberry pink
        accent_dk="#c84468",    # deeper berry
        accent_hv="#f07098",    # light strawberry hover
        accent_pr="#a83858",    # pressed berry
        bg="#fffaf8",           # peach cream white
        surface="#fff0ee",      # very light strawberry milk
        elevated="#ffffff",     # pure white
        hover="#ffe4e0",        # light blush hover
        sidebar="#e8fff0ee",    # blush sidebar
        text1="#3a1820",        # deep berry text
        text2="#7a4858",        # muted berry
        text3="#b08898",        # light mauve
        text_dis="#d0b8c0",     # faded rose
        accent_faint="#ffe0e8", # very light pink tint
    ),
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

MESSAGE_MAX_WIDTH = 680
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
