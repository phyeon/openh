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


# 1. Default Blue
_register_preset("Blue (Default)", DARK, LIGHT)

# 2. Mocha (warm brown, Pantone 2025 vibes)
_MOCHA_ACCENT = "#A47864"
_register_preset("Mocha", Tokens(
    BG_SIDEBAR="#e01c1916", BG_DEEPEST="#161310", BG_PAGE="#1e1b18",
    BG_ELEVATED="#2a2622", BG_HOVER="#302b26", BG_SIDEBAR_SELECTED="#252118",
    BG_STATUS="#161310",
    TEXT_PRIMARY="#F0E8DC", TEXT_SECONDARY="#B8AFA0", TEXT_TERTIARY="#807868",
    TEXT_DISABLED="#585048", TEXT_ON_ACCENT="#ffffff",
    ACCENT=_MOCHA_ACCENT, ACCENT_DARK="#8C6450", ACCENT_HOVER="#BA8E78",
    ACCENT_PRESSED="#7A5842", ACCENT_FAINT="#2e2218",
    BORDER_FAINT="#282420", BORDER_SUBTLE="#36302a", BORDER_STRONG="#4a4238",
    ERROR="#E85D5D", WARN="#E8A555", SUCCESS="#86BE6B",
    TOOL_CALL_BG="#241e18", TOOL_CALL_BORDER="#3a3028",
    TOOL_RESULT_BG="#1e1c18", TOOL_RESULT_BORDER="#2e2a22",
    ERROR_BG="#2c1a1a",
), Tokens(
    BG_PAGE="#faf8f5", BG_SIDEBAR="#e8f0eee8", BG_DEEPEST="#e8e4e0",
    BG_ELEVATED="#ffffff", BG_HOVER="#ece8e2", BG_SIDEBAR_SELECTED="#e0dbd4",
    BG_STATUS="#eae6e0",
    TEXT_PRIMARY="#1a1816", TEXT_SECONDARY="#4a4640", TEXT_TERTIARY="#7a7268",
    TEXT_DISABLED="#b0a89c", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#A06850", ACCENT_DARK="#885840", ACCENT_HOVER="#B87860",
    ACCENT_PRESSED="#784830", ACCENT_FAINT="#f0ddd0",
    BORDER_FAINT="#e0dcd6", BORDER_SUBTLE="#d0c8c0", BORDER_STRONG="#a09890",
    ERROR="#d03838", WARN="#c07a1c", SUCCESS="#3aa169",
    TOOL_CALL_BG="#f5ede4", TOOL_CALL_BORDER="#dcc8b0",
    TOOL_RESULT_BG="#eef0f2", TOOL_RESULT_BORDER="#c8d0d8",
    ERROR_BG="#fde8e8",
))

# 3. Forest (green accent)
_register_preset("Forest", Tokens(
    BG_SIDEBAR="#e0141816", BG_DEEPEST="#101412", BG_PAGE="#181c1a",
    BG_ELEVATED="#222826", BG_HOVER="#282e2c", BG_SIDEBAR_SELECTED="#1c2220",
    BG_STATUS="#101412",
    TEXT_PRIMARY="#E4EAE6", TEXT_SECONDARY="#9CA8A0", TEXT_TERTIARY="#687870",
    TEXT_DISABLED="#485850", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#5EA87A", ACCENT_DARK="#4A9066", ACCENT_HOVER="#78C094",
    ACCENT_PRESSED="#408858", ACCENT_FAINT="#1a2c22",
    BORDER_FAINT="#202826", BORDER_SUBTLE="#2c3432", BORDER_STRONG="#3c4844",
    ERROR="#EF6461", WARN="#E8A555", SUCCESS="#6BCB77",
    TOOL_CALL_BG="#1a2420", TOOL_CALL_BORDER="#283830",
    TOOL_RESULT_BG="#181e1c", TOOL_RESULT_BORDER="#243028",
    ERROR_BG="#2c1a1a",
), Tokens(
    BG_PAGE="#f5faf7", BG_SIDEBAR="#e8eceee8", BG_DEEPEST="#e4ebe6",
    BG_ELEVATED="#ffffff", BG_HOVER="#e0eae4", BG_SIDEBAR_SELECTED="#d8e4dc",
    BG_STATUS="#e4ebe6",
    TEXT_PRIMARY="#141c18", TEXT_SECONDARY="#3a4a40", TEXT_TERTIARY="#607868",
    TEXT_DISABLED="#a0b0a8", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#3E8A5C", ACCENT_DARK="#2E7A4C", ACCENT_HOVER="#50A070",
    ACCENT_PRESSED="#206838", ACCENT_FAINT="#d4eede",
    BORDER_FAINT="#dce6e0", BORDER_SUBTLE="#c8d4cc", BORDER_STRONG="#98a8a0",
    ERROR="#d03838", WARN="#c07a1c", SUCCESS="#3aa169",
    TOOL_CALL_BG="#e8f2ec", TOOL_CALL_BORDER="#b8d0c0",
    TOOL_RESULT_BG="#eef2f0", TOOL_RESULT_BORDER="#c4d4cc",
    ERROR_BG="#fde8e8",
))

# 4. Sunset (orange/coral accent)
_register_preset("Sunset", Tokens(
    BG_SIDEBAR="#e01a1614", BG_DEEPEST="#141210", BG_PAGE="#1e1a18",
    BG_ELEVATED="#2a2624", BG_HOVER="#302c28", BG_SIDEBAR_SELECTED="#241e1c",
    BG_STATUS="#141210",
    TEXT_PRIMARY="#F0E8E4", TEXT_SECONDARY="#B0A8A0", TEXT_TERTIARY="#807870",
    TEXT_DISABLED="#585048", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#E87040", ACCENT_DARK="#D06030", ACCENT_HOVER="#F08858",
    ACCENT_PRESSED="#C05028", ACCENT_FAINT="#2e1c14",
    BORDER_FAINT="#282420", BORDER_SUBTLE="#36302c", BORDER_STRONG="#4a4440",
    ERROR="#EF6461", WARN="#E8A555", SUCCESS="#6BCB77",
    TOOL_CALL_BG="#241c18", TOOL_CALL_BORDER="#3a2c20",
    TOOL_RESULT_BG="#1e1a18", TOOL_RESULT_BORDER="#2e2820",
    ERROR_BG="#2c1a1a",
), Tokens(
    BG_PAGE="#fdf8f5", BG_SIDEBAR="#e8f2eee8", BG_DEEPEST="#ece6e0",
    BG_ELEVATED="#ffffff", BG_HOVER="#f0e8e2", BG_SIDEBAR_SELECTED="#e8dcd4",
    BG_STATUS="#ece6e0",
    TEXT_PRIMARY="#1c1816", TEXT_SECONDARY="#4a4440", TEXT_TERTIARY="#7a706a",
    TEXT_DISABLED="#b0a8a0", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#D86030", ACCENT_DARK="#C04820", ACCENT_HOVER="#E87848",
    ACCENT_PRESSED="#B04018", ACCENT_FAINT="#fcdccc",
    BORDER_FAINT="#e4dcd6", BORDER_SUBTLE="#d4ccc4", BORDER_STRONG="#a8a098",
    ERROR="#d03838", WARN="#c07a1c", SUCCESS="#3aa169",
    TOOL_CALL_BG="#f8ede4", TOOL_CALL_BORDER="#e0c4a8",
    TOOL_RESULT_BG="#f0f0f2", TOOL_RESULT_BORDER="#c8ccd4",
    ERROR_BG="#fde8e8",
))

# 5. Lavender (purple accent)
_register_preset("Lavender", Tokens(
    BG_SIDEBAR="#e0171618", BG_DEEPEST="#121014", BG_PAGE="#1a181e",
    BG_ELEVATED="#24222a", BG_HOVER="#2a2830", BG_SIDEBAR_SELECTED="#1e1c24",
    BG_STATUS="#121014",
    TEXT_PRIMARY="#E8E6EE", TEXT_SECONDARY="#A09CAC", TEXT_TERTIARY="#6C687A",
    TEXT_DISABLED="#4a4856", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#9B7ADB", ACCENT_DARK="#8568C4", ACCENT_HOVER="#B494EF",
    ACCENT_PRESSED="#7558B0", ACCENT_FAINT="#221C30",
    BORDER_FAINT="#222028", BORDER_SUBTLE="#2e2c36", BORDER_STRONG="#403c4a",
    ERROR="#EF6461", WARN="#E8A555", SUCCESS="#6BCB77",
    TOOL_CALL_BG="#1e1a26", TOOL_CALL_BORDER="#2c2840",
    TOOL_RESULT_BG="#1a1820", TOOL_RESULT_BORDER="#262234",
    ERROR_BG="#2c1a1a",
), Tokens(
    BG_PAGE="#fafafc", BG_SIDEBAR="#e8f0f0f4", BG_DEEPEST="#eceaf0",
    BG_ELEVATED="#ffffff", BG_HOVER="#e8e6ee", BG_SIDEBAR_SELECTED="#e0dce8",
    BG_STATUS="#eceaf0",
    TEXT_PRIMARY="#1a181e", TEXT_SECONDARY="#444050", TEXT_TERTIARY="#706880",
    TEXT_DISABLED="#a8a0b0", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#7B5CC0", ACCENT_DARK="#6848A8", ACCENT_HOVER="#9070D8",
    ACCENT_PRESSED="#5838A0", ACCENT_FAINT="#e4d8f4",
    BORDER_FAINT="#e0dce6", BORDER_SUBTLE="#d0c8d8", BORDER_STRONG="#a098b0",
    ERROR="#d03838", WARN="#c07a1c", SUCCESS="#3aa169",
    TOOL_CALL_BG="#f0ecf6", TOOL_CALL_BORDER="#c8bce0",
    TOOL_RESULT_BG="#eeeef4", TOOL_RESULT_BORDER="#c4c0d4",
    ERROR_BG="#fde8e8",
))

# 6. Midnight (deep navy, cyan accent)
_register_preset("Midnight", Tokens(
    BG_SIDEBAR="#e00c1018", BG_DEEPEST="#080c12", BG_PAGE="#101420",
    BG_ELEVATED="#1a1e2c", BG_HOVER="#202432", BG_SIDEBAR_SELECTED="#141828",
    BG_STATUS="#080c12",
    TEXT_PRIMARY="#D8E0F0", TEXT_SECONDARY="#8890A8", TEXT_TERTIARY="#586078",
    TEXT_DISABLED="#384058", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#40B8D8", ACCENT_DARK="#30A0C0", ACCENT_HOVER="#58D0F0",
    ACCENT_PRESSED="#2890A8", ACCENT_FAINT="#102030",
    BORDER_FAINT="#182030", BORDER_SUBTLE="#202838", BORDER_STRONG="#303848",
    ERROR="#EF6461", WARN="#E8A555", SUCCESS="#6BCB77",
    TOOL_CALL_BG="#101828", TOOL_CALL_BORDER="#1c2840",
    TOOL_RESULT_BG="#0e1420", TOOL_RESULT_BORDER="#182238",
    ERROR_BG="#2c1a1a",
), Tokens(
    BG_PAGE="#f4f8fc", BG_SIDEBAR="#e8e4ecf4", BG_DEEPEST="#e0e8f0",
    BG_ELEVATED="#ffffff", BG_HOVER="#dce4ee", BG_SIDEBAR_SELECTED="#d0dce8",
    BG_STATUS="#e0e8f0",
    TEXT_PRIMARY="#0c1020", TEXT_SECONDARY="#2c3850", TEXT_TERTIARY="#506078",
    TEXT_DISABLED="#90a0b0", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#1890B0", ACCENT_DARK="#107898", ACCENT_HOVER="#30A8C8",
    ACCENT_PRESSED="#086888", ACCENT_FAINT="#d0e8f4",
    BORDER_FAINT="#dce4ec", BORDER_SUBTLE="#c8d4e0", BORDER_STRONG="#90a0b0",
    ERROR="#d03838", WARN="#c07a1c", SUCCESS="#3aa169",
    TOOL_CALL_BG="#e4eef6", TOOL_CALL_BORDER="#b0c8dc",
    TOOL_RESULT_BG="#eaf0f4", TOOL_RESULT_BORDER="#bcc8d8",
    ERROR_BG="#fde8e8",
))

# 7. Rose (pink accent)
_ROSE_ACC = "#D86888"
_register_preset("Rose", Tokens(
    BG_SIDEBAR="#e01a1618", BG_DEEPEST="#141014", BG_PAGE="#1e181c",
    BG_ELEVATED="#282228", BG_HOVER="#2e282e", BG_SIDEBAR_SELECTED="#221c22",
    BG_STATUS="#141014",
    TEXT_PRIMARY="#F0E6EC", TEXT_SECONDARY="#B0A4AC", TEXT_TERTIARY="#78707A",
    TEXT_DISABLED="#504850", TEXT_ON_ACCENT="#ffffff",
    ACCENT=_ROSE_ACC, ACCENT_DARK="#C05878", ACCENT_HOVER="#E880A0",
    ACCENT_PRESSED="#B04868", ACCENT_FAINT="#2c1820",
    BORDER_FAINT="#262024", BORDER_SUBTLE="#342C32", BORDER_STRONG="#483E44",
    ERROR="#EF6461", WARN="#E8A555", SUCCESS="#6BCB77",
    TOOL_CALL_BG="#221a20", TOOL_CALL_BORDER="#382830",
    TOOL_RESULT_BG="#1c181c", TOOL_RESULT_BORDER="#2a2228",
    ERROR_BG="#2c1a1a",
), Tokens(
    BG_PAGE="#fcf8fa", BG_SIDEBAR="#e8f2eef0", BG_DEEPEST="#eee8ec",
    BG_ELEVATED="#ffffff", BG_HOVER="#f0e8ee", BG_SIDEBAR_SELECTED="#e8dee6",
    BG_STATUS="#eee8ec",
    TEXT_PRIMARY="#1c161a", TEXT_SECONDARY="#4a4048", TEXT_TERTIARY="#786870",
    TEXT_DISABLED="#b0a4a8", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#C05070", ACCENT_DARK="#A84060", ACCENT_HOVER="#D86888",
    ACCENT_PRESSED="#983858", ACCENT_FAINT="#f4d8e0",
    BORDER_FAINT="#e6dee2", BORDER_SUBTLE="#d4ccd0", BORDER_STRONG="#a8a0a4",
    ERROR="#d03838", WARN="#c07a1c", SUCCESS="#3aa169",
    TOOL_CALL_BG="#f6ecf0", TOOL_CALL_BORDER="#dcc0cc",
    TOOL_RESULT_BG="#f0eef2", TOOL_RESULT_BORDER="#ccc4d0",
    ERROR_BG="#fde8e8",
))

# 8. Slate (neutral gray, no color accent)
_register_preset("Slate", Tokens(
    BG_SIDEBAR="#e0161618", BG_DEEPEST="#101012", BG_PAGE="#1a1a1c",
    BG_ELEVATED="#242426", BG_HOVER="#2a2a2c", BG_SIDEBAR_SELECTED="#1e1e22",
    BG_STATUS="#101012",
    TEXT_PRIMARY="#E0E0E4", TEXT_SECONDARY="#98989E", TEXT_TERTIARY="#686870",
    TEXT_DISABLED="#484850", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#8890A0", ACCENT_DARK="#707888", ACCENT_HOVER="#A0A8B8",
    ACCENT_PRESSED="#606878", ACCENT_FAINT="#1c1c24",
    BORDER_FAINT="#222224", BORDER_SUBTLE="#2e2e32", BORDER_STRONG="#404044",
    ERROR="#EF6461", WARN="#E8A555", SUCCESS="#6BCB77",
    TOOL_CALL_BG="#1c1c22", TOOL_CALL_BORDER="#2a2a34",
    TOOL_RESULT_BG="#181820", TOOL_RESULT_BORDER="#24242e",
    ERROR_BG="#2c1a1a",
), Tokens(
    BG_PAGE="#f8f8fa", BG_SIDEBAR="#e8f0f0f2", BG_DEEPEST="#eaeaee",
    BG_ELEVATED="#ffffff", BG_HOVER="#e6e6ea", BG_SIDEBAR_SELECTED="#dcdce2",
    BG_STATUS="#eaeaee",
    TEXT_PRIMARY="#18181c", TEXT_SECONDARY="#444448", TEXT_TERTIARY="#6c6c74",
    TEXT_DISABLED="#a8a8ae", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#606878", ACCENT_DARK="#505868", ACCENT_HOVER="#707888",
    ACCENT_PRESSED="#404858", ACCENT_FAINT="#dce0e8",
    BORDER_FAINT="#e0e0e4", BORDER_SUBTLE="#d0d0d6", BORDER_STRONG="#a0a0a8",
    ERROR="#d03838", WARN="#c07a1c", SUCCESS="#3aa169",
    TOOL_CALL_BG="#eeeef2", TOOL_CALL_BORDER="#c4c4cc",
    TOOL_RESULT_BG="#eef0f2", TOOL_RESULT_BORDER="#c4c8d0",
    ERROR_BG="#fde8e8",
))

# 9. Gold (warm gold accent)
_register_preset("Gold", Tokens(
    BG_SIDEBAR="#e01a1814", BG_DEEPEST="#141210", BG_PAGE="#1c1a16",
    BG_ELEVATED="#28261e", BG_HOVER="#2e2c24", BG_SIDEBAR_SELECTED="#22201a",
    BG_STATUS="#141210",
    TEXT_PRIMARY="#EEE8D8", TEXT_SECONDARY="#AEA890", TEXT_TERTIARY="#787060",
    TEXT_DISABLED="#504C40", TEXT_ON_ACCENT="#1a1810",
    ACCENT="#D4A848", ACCENT_DARK="#B89038", ACCENT_HOVER="#E8BC60",
    ACCENT_PRESSED="#A08030", ACCENT_FAINT="#282010",
    BORDER_FAINT="#242218", BORDER_SUBTLE="#322E24", BORDER_STRONG="#464034",
    ERROR="#EF6461", WARN="#E8A555", SUCCESS="#6BCB77",
    TOOL_CALL_BG="#221e14", TOOL_CALL_BORDER="#362E1C",
    TOOL_RESULT_BG="#1e1c16", TOOL_RESULT_BORDER="#2a2618",
    ERROR_BG="#2c1a1a",
), Tokens(
    BG_PAGE="#fcfaf5", BG_SIDEBAR="#e8f0ece4", BG_DEEPEST="#ece8e0",
    BG_ELEVATED="#ffffff", BG_HOVER="#f0ece4", BG_SIDEBAR_SELECTED="#e6e0d4",
    BG_STATUS="#ece8e0",
    TEXT_PRIMARY="#1a1810", TEXT_SECONDARY="#48443a", TEXT_TERTIARY="#787060",
    TEXT_DISABLED="#b0a898", TEXT_ON_ACCENT="#1a1810",
    ACCENT="#B08828", ACCENT_DARK="#987018", ACCENT_HOVER="#C8A040",
    ACCENT_PRESSED="#886010", ACCENT_FAINT="#f4e8c8",
    BORDER_FAINT="#e4e0d6", BORDER_SUBTLE="#d4ccc0", BORDER_STRONG="#a8a090",
    ERROR="#d03838", WARN="#c07a1c", SUCCESS="#3aa169",
    TOOL_CALL_BG="#f8f0e0", TOOL_CALL_BORDER="#dcc8a0",
    TOOL_RESULT_BG="#f0f0ec", TOOL_RESULT_BORDER="#c8c8c0",
    ERROR_BG="#fde8e8",
))

# 10. Abyss (AMOLED black, blue accent)
_register_preset("Abyss", Tokens(
    BG_SIDEBAR="#e0040408", BG_DEEPEST="#000000", BG_PAGE="#080810",
    BG_ELEVATED="#101018", BG_HOVER="#181820", BG_SIDEBAR_SELECTED="#0c0c14",
    BG_STATUS="#000000",
    TEXT_PRIMARY="#D0D4E0", TEXT_SECONDARY="#7880A0", TEXT_TERTIARY="#485068",
    TEXT_DISABLED="#303848", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#5080F0", ACCENT_DARK="#4068D0", ACCENT_HOVER="#6898FF",
    ACCENT_PRESSED="#3858B8", ACCENT_FAINT="#101830",
    BORDER_FAINT="#101018", BORDER_SUBTLE="#181828", BORDER_STRONG="#282838",
    ERROR="#EF6461", WARN="#E8A555", SUCCESS="#6BCB77",
    TOOL_CALL_BG="#080818", TOOL_CALL_BORDER="#141830",
    TOOL_RESULT_BG="#060614", TOOL_RESULT_BORDER="#101828",
    ERROR_BG="#200808",
), Tokens(
    BG_PAGE="#fafbfc", BG_SIDEBAR="#e8f2f3f5", BG_DEEPEST="#ebedf0",
    BG_ELEVATED="#ffffff", BG_HOVER="#e8eaed", BG_SIDEBAR_SELECTED="#e1e4e8",
    BG_STATUS="#ebedf0",
    TEXT_PRIMARY="#1a1c20", TEXT_SECONDARY="#444952", TEXT_TERTIARY="#6b7280",
    TEXT_DISABLED="#a0a5ae", TEXT_ON_ACCENT="#ffffff",
    ACCENT="#4878DB", ACCENT_DARK="#3660B8", ACCENT_HOVER="#5E8CE6",
    ACCENT_PRESSED="#3358A8", ACCENT_FAINT="#dfe8f8",
    BORDER_FAINT="#e2e5ea", BORDER_SUBTLE="#d0d4db", BORDER_STRONG="#a0a6b0",
    ERROR="#d03838", WARN="#c07a1c", SUCCESS="#3aa169",
    TOOL_CALL_BG="#edf1fa", TOOL_CALL_BORDER="#c4d0e8",
    TOOL_RESULT_BG="#eef2f7", TOOL_RESULT_BORDER="#c8d1de",
    ERROR_BG="#fde8e8",
))


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
