"""Claude.app-inspired Flet widgets.

Layout reference (what Claude.app actually looks like):
  ┌──────────┬──────────────────────────────────┐
  │ sidebar  │  (top nav — empty / model pill) │
  │          ├──────────────────────────────────┤
  │ + New    │                                  │
  │          │        centered message          │
  │ Recents  │        column (max 760px)        │
  │  · chat1 │                                  │
  │  · chat2 │      ┌────────────────────┐      │
  │          │      │ rounded input box  │      │
  │  profile │      │ [+] [tools]    [↑] │      │
  │          │      └────────────────────┘      │
  └──────────┴──────────────────────────────────┘

Colors sampled from Claude.app's actual CSS variables (dark mode):
  sidebar = #1F1E1B, main = #262624, text = #F8F4E8, accent = #D97757
"""
from __future__ import annotations

import json
import re
from typing import Callable

import flet as ft

from ..pricing import estimate_cost_usd
from . import theme


# ============================================================================
#  Sidebar
# ============================================================================

def sidebar(
    groups: dict[str, list[tuple[str, str, str, bool, bool]]],
    # group -> [(session_id, title, project_display, starred, hidden), ...]
    active_session_id: str,
    on_new_chat: Callable,
    on_select: Callable[[str], None],
    on_delete: Callable[[str], None],
    on_star: Callable[[str], None] | None = None,
    on_hide: Callable[[str], None] | None = None,
    on_toggle_hidden: Callable[[], None] | None = None,
    show_hidden: bool = False,
    user_label: str = "openh",
    width: int = theme.SIDEBAR_WIDTH,
    profiles: list | None = None,
    on_new_profile: Callable[[str], None] | None = None,
    active_profile=None,
) -> ft.Container:
    """Left navigation rail with [+ New chat], grouped session list."""

    active_accent = getattr(active_profile, "accent_color", "") if active_profile is not None else ""
    is_fnd = theme.is_fnd()
    new_chat_btn = ft.IconButton(
        icon=ft.Icons.EDIT_SQUARE,
        icon_color=active_accent or theme.TEXT_PRIMARY,
        icon_size=18,
        tooltip=(
            f"New chat ({active_profile.display_name})"
            if active_profile is not None
            else "New chat"
        ),
        on_click=lambda e: on_new_chat(),
        style=ft.ButtonStyle(
            shape=ft.CircleBorder(),
            padding=ft.padding.all(8),
            bgcolor=(
                "#10192a" if is_fnd and theme.is_dark() else ("#fff4ed" if is_fnd else None)
            ),
            overlay_color=theme.BG_HOVER,
        ),
    )

    def group_label(text: str) -> ft.Container:
        return ft.Container(
            content=ft.Text(
                text,
                color=theme.TEXT_TERTIARY,
                size=11,
                weight=ft.FontWeight.W_600,
            ),
            padding=ft.padding.only(left=14, top=14, bottom=4),
        )

    def session_item(
        session_id: str, title: str, project: str,
        starred: bool = False, hidden: bool = False,
    ) -> ft.Container:
        selected = session_id == active_session_id

        star_icon = ft.Icon(
            ft.Icons.STAR if starred else ft.Icons.STAR_BORDER,
            color=theme.ACCENT if starred else theme.TEXT_TERTIARY,
            size=13,
        ) if starred else None  # only show if starred

        title_row_children: list[ft.Control] = []
        if star_icon:
            title_row_children.append(star_icon)
        title_row_children.append(
            ft.Text(
                title or "Untitled",
                color=theme.TEXT_PRIMARY if selected else theme.TEXT_SECONDARY,
                size=13,
                overflow=ft.TextOverflow.ELLIPSIS,
                max_lines=1,
                expand=True,
                opacity=0.5 if hidden else 1.0,
            ),
        )

        # Context menu items
        menu_items = []
        if on_star:
            menu_items.append(
                ft.PopupMenuItem(
                    content="Unstar" if starred else "Star",
                    icon=ft.Icons.STAR_BORDER if starred else ft.Icons.STAR,
                    on_click=lambda e, sid=session_id: on_star(sid),
                )
            )
        if on_hide:
            menu_items.append(
                ft.PopupMenuItem(
                    content="Unhide" if hidden else "Hide",
                    icon=ft.Icons.VISIBILITY if hidden else ft.Icons.VISIBILITY_OFF,
                    on_click=lambda e, sid=session_id: on_hide(sid),
                )
            )
        menu_items.append(
            ft.PopupMenuItem(
                content="Delete",
                icon=ft.Icons.DELETE_OUTLINE,
                on_click=lambda e, sid=session_id: on_delete(sid),
            )
        )

        action_btn = ft.PopupMenuButton(
            items=menu_items,
            icon=ft.Icons.MORE_HORIZ,
            icon_color=theme.TEXT_TERTIARY,
            icon_size=15,
            tooltip="Actions",
            padding=ft.padding.all(0),
            visible=selected,
        )

        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Row(title_row_children, spacing=4, tight=True),
                            ft.Text(
                                project,
                                color=theme.TEXT_TERTIARY,
                                size=10,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                max_lines=1,
                                font_family=theme.FONT_MONO,
                            ) if project else ft.Container(),
                        ],
                        spacing=1,
                        tight=True,
                        expand=True,
                    ),
                    action_btn,
                ],
                spacing=4,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(left=12, right=6, top=7, bottom=7),
            bgcolor=theme.BG_SIDEBAR_SELECTED if selected else None,
            border_radius=theme.RADIUS_SM,
            on_click=lambda e, sid=session_id: on_select(sid),
            ink=True,
            margin=ft.margin.symmetric(horizontal=8, vertical=1),
        )

    body_children: list[ft.Control] = []
    if not groups:
        body_children.append(
            ft.Container(
                content=ft.Text(
                    "No conversations yet",
                    color=theme.TEXT_TERTIARY,
                    size=12,
                    italic=True,
                ),
                padding=ft.padding.only(left=14, top=12),
            )
        )
    else:
        for gname, items in groups.items():
            body_children.append(group_label(gname))
            for item in items:
                sid, title, project = item[0], item[1], item[2]
                starred = item[3] if len(item) > 3 else False
                hidden = item[4] if len(item) > 4 else False
                if hidden and not show_hidden:
                    continue
                body_children.append(session_item(sid, title, project, starred, hidden))

    top_section = [
        ft.Container(content=new_chat_btn, padding=ft.padding.only(left=8, top=8, bottom=4)),
    ]

    # Count hidden sessions
    hidden_count = sum(
        1
        for items in groups.values()
        for item in items
        if len(item) > 4 and item[4]
    )

    bottom_section: list[ft.Control] = []
    if hidden_count > 0 or show_hidden:
        toggle_label = f"Hide hidden ({hidden_count})" if show_hidden else f"Show hidden ({hidden_count})"
        toggle_icon = ft.Icons.VISIBILITY_OFF if show_hidden else ft.Icons.VISIBILITY
        bottom_section.append(
            ft.Container(
                content=ft.TextButton(
                    content=ft.Row(
                        [
                            ft.Icon(toggle_icon, size=14, color=theme.TEXT_TERTIARY),
                            ft.Text(toggle_label, size=11, color=theme.TEXT_TERTIARY),
                        ],
                        spacing=4,
                    ),
                    on_click=lambda _: on_toggle_hidden() if on_toggle_hidden else None,
                ),
                padding=ft.padding.only(left=8, bottom=8),
            )
        )

    return ft.Container(
        width=width,
        bgcolor=theme.BG_SIDEBAR,
        content=ft.Column(
            [
                *top_section,
                ft.Container(
                    content=ft.Column(
                        body_children,
                        spacing=0,
                        tight=False,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    expand=True,
                ),
                *bottom_section,
            ],
            spacing=0,
            expand=True,
        ),
    )


# ============================================================================
#  Top bar (conversation title + sidebar toggle)
# ============================================================================

def top_bar(
    title: str,
    on_toggle_sidebar: Callable,
    on_rename: Callable,
    on_toggle_theme: Callable,
    on_open_settings: Callable,
    on_edit_prompt: Callable | None = None,
    prompt_label: str = "",
    busy_indicator: ft.Control | None = None,
) -> ft.Container:
    """Conversation title bar — claude.app style with sidebar toggle on the left."""
    is_fnd = theme.is_fnd()
    dark_fnd = is_fnd and theme.is_dark()

    toggle_btn = ft.IconButton(
        icon=ft.Icons.VIEW_SIDEBAR_OUTLINED,
        icon_color=theme.TEXT_SECONDARY,
        icon_size=18,
        tooltip="Toggle sidebar",
        on_click=lambda e: on_toggle_sidebar(),
        style=ft.ButtonStyle(
            shape=ft.CircleBorder(),
            padding=ft.padding.all(6),
            overlay_color=theme.BG_HOVER,
        ),
    )

    theme_btn = ft.IconButton(
        icon=ft.Icons.BRIGHTNESS_6_OUTLINED,
        icon_color=theme.TEXT_SECONDARY,
        icon_size=18,
        tooltip="Toggle light/dark mode",
        on_click=lambda e: on_toggle_theme(),
        style=ft.ButtonStyle(
            shape=ft.CircleBorder(),
            padding=ft.padding.all(6),
            overlay_color=theme.BG_HOVER,
        ),
    )

    settings_btn = ft.IconButton(
        icon=ft.Icons.SETTINGS_OUTLINED,
        icon_color=theme.TEXT_SECONDARY,
        icon_size=18,
        tooltip="Settings (⌘,)",
        on_click=lambda e: on_open_settings(),
        style=ft.ButtonStyle(
            shape=ft.CircleBorder(),
            padding=ft.padding.all(6),
            overlay_color=theme.BG_HOVER,
        ),
    )

    if is_fnd:
        marker = ft.Container(
            width=4,
            height=20,
            border_radius=999,
            bgcolor=theme.ACCENT,
            opacity=0.8,
        )
        title_widget = ft.Container(
            content=ft.Row(
                [
                    marker,
                    ft.Container(width=8),
                    ft.Text(
                        title or "New chat",
                        color=theme.TEXT_PRIMARY,
                        size=16,
                        weight=ft.FontWeight.W_600,
                        font_family=theme.FONT_EM,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                        expand=True,
                    ),
                ],
                spacing=0,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=4, vertical=6),
            ink=True,
            on_click=lambda e: on_rename(),
            tooltip="Click to rename conversation",
            expand=True,
        )
    else:
        title_widget = ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        title or "New chat",
                        color=theme.TEXT_PRIMARY,
                        size=14,
                        weight=ft.FontWeight.W_500,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        max_lines=1,
                        expand=True,
                    ),
                    ft.Icon(
                        ft.Icons.KEYBOARD_ARROW_DOWN,
                        color=theme.TEXT_TERTIARY,
                        size=16,
                    ),
                ],
                spacing=4,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            border_radius=theme.RADIUS_SM,
            ink=True,
            on_click=lambda e: on_rename(),
            tooltip="Click to rename conversation",
            expand=True,
        )

    note_text = busy_indicator or ft.Container()
    if on_edit_prompt:
        if is_fnd:
            prompt_control = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(
                            ft.Icons.ARTICLE_OUTLINED,
                            color=theme.ACCENT if dark_fnd else theme.TEXT_SECONDARY,
                            size=14,
                        ),
                        ft.Text(
                            (prompt_label or "default").replace("(edited)", "").strip() or "default",
                            color=theme.TEXT_SECONDARY,
                            size=11,
                            font_family=theme.FONT_MONO,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ],
                    spacing=6,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                padding=ft.padding.symmetric(horizontal=10, vertical=6),
                border_radius=theme.RADIUS_PILL,
                border=ft.border.all(1, theme.BORDER_FAINT),
                bgcolor=theme.BG_ELEVATED,
                ink=True,
                on_click=lambda e: on_edit_prompt(),
                tooltip=f"Edit prompt ({prompt_label or 'default'})",
            )
        else:
            prompt_control = ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.ARTICLE_OUTLINED, color=theme.TEXT_TERTIARY, size=13),
                        ft.Text(
                            prompt_label or "default",
                            color=theme.TEXT_TERTIARY,
                            size=11,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            expand=True,
                        ),
                    ],
                    spacing=4,
                    tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                width=120,
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                border_radius=theme.RADIUS_PILL,
                border=ft.border.all(1, theme.BORDER_FAINT),
                on_click=lambda e: on_edit_prompt(),
                ink=True,
                tooltip="Edit session prompt",
            )
    else:
        prompt_control = ft.Container()

    return ft.Container(
        height=56 if is_fnd else theme.TOP_BAR_HEIGHT,
        bgcolor=theme.BG_PAGE,
        content=ft.Row(
            [
                toggle_btn,
                ft.Container(width=4),
                title_widget,
                ft.Container(expand=True),
                note_text,
                ft.Container(width=8),
                prompt_control,
                ft.Container(width=4),
                theme_btn,
                settings_btn,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(horizontal=16),
        border=ft.border.only(
            bottom=ft.BorderSide(1, theme.BORDER_FAINT),
        ),
    )


def _estimate_cost(
    model: str,
    in_tokens: int,
    out_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Rough USD cost estimate based on published pricing (per 1M tokens)."""
    return estimate_cost_usd(
        model,
        in_tokens,
        out_tokens,
        cache_creation_tokens,
        cache_read_tokens,
    )


def _format_cost(cost: float) -> str:
    if cost < 0.01:
        return f"${cost:.4f}"
    if cost < 1.0:
        return f"${cost:.3f}"
    return f"${cost:.2f}"


def bottom_status_bar(
    cwd: str,
    in_tokens: int,
    out_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    subagent_total_tokens: int = 0,
    model: str = "",
    cost_usd: float | None = None,
    context_tokens: int = 0,
    context_limit: int = 200_000,
) -> ft.Container:
    """Thin status strip — cwd + token counts + cost estimate + context usage."""
    cost = (
        cost_usd
        if cost_usd is not None
        else _estimate_cost(
            model,
            in_tokens,
            out_tokens,
            cache_creation_tokens,
            cache_read_tokens,
        )
    )
    cost_str = _format_cost(cost)
    total_tokens = (
        in_tokens
        + out_tokens
        + cache_creation_tokens
        + cache_read_tokens
    )
    token_label = f"Σ {total_tokens:,} · in {in_tokens:,} · out {out_tokens:,}"
    cache_label = ""
    if cache_creation_tokens or cache_read_tokens:
        cache_label = f"cache +{cache_creation_tokens:,}/{cache_read_tokens:,}"
    agent_label = ""
    if subagent_total_tokens > 0:
        agent_label = f"agents {subagent_total_tokens:,}"

    right_parts = [
        ft.Text(
            token_label,
            color=theme.TEXT_TERTIARY,
            size=11,
            font_family=theme.FONT_MONO,
        ),
    ]
    if cache_label:
        right_parts.append(
            ft.Text(
                cache_label,
                color=theme.TEXT_TERTIARY,
                size=11,
                font_family=theme.FONT_MONO,
            )
        )
    if agent_label:
        right_parts.append(
            ft.Text(
                agent_label,
                color=theme.ACCENT,
                size=11,
                font_family=theme.FONT_MONO,
            )
        )
    right_parts.extend(
        [
        ft.Text(
            cost_str,
            color=theme.ACCENT if cost > 0.01 else theme.TEXT_TERTIARY,
            size=11,
            font_family=theme.FONT_MONO,
        ),
        ]
    )

    # Context usage bar
    if context_tokens > 0 and context_limit > 0:
        pct = min(context_tokens / context_limit, 1.0)
        pct_color = theme.SUCCESS if pct < 0.5 else (theme.WARN if pct < 0.8 else theme.ERROR)
        right_parts.append(
            ft.Row(
                [
                    ft.Container(
                        width=40,
                        height=4,
                        border_radius=2,
                        bgcolor=theme.BORDER_FAINT,
                        content=ft.Container(
                            width=int(40 * pct),
                            height=4,
                            border_radius=2,
                            bgcolor=pct_color,
                        ),
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ),
                    ft.Text(
                        f"{int(pct * 100)}%",
                        color=pct_color,
                        size=10,
                        font_family=theme.FONT_MONO,
                    ),
                ],
                spacing=4,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )

    return ft.Container(
        height=theme.STATUS_BAR_HEIGHT,
        bgcolor=theme.BG_STATUS,
        content=ft.Row(
            [
                ft.Icon(ft.Icons.FOLDER_OPEN, color=theme.TEXT_TERTIARY, size=13),
                ft.Text(
                    cwd,
                    color=theme.TEXT_TERTIARY,
                    size=11,
                    font_family=theme.FONT_MONO,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    max_lines=1,
                    expand=True,
                ),
                *right_parts,
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(horizontal=14),
        border=ft.border.only(top=ft.BorderSide(1, theme.BORDER_FAINT)),
    )


# ============================================================================
#  Messages
# ============================================================================

_ANTML_THINKING_RE = re.compile(
    r"<antml:thinking\b[^>]*>(.*?)</antml:thinking>",
    re.IGNORECASE | re.DOTALL,
)
_ANTML_THINKING_OPEN_PREFIX = "<antml:thinking"
_ANTML_THINKING_CLOSE = "</antml:thinking>"


def _extract_antml_thinking(markdown_text: str) -> tuple[list[str], str]:
    thoughts: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        thought = (match.group(1) or "").strip()
        if thought:
            thoughts.append(thought)
        return ""

    visible = _ANTML_THINKING_RE.sub(_replace, markdown_text or "")
    visible = re.sub(r"\n{3,}", "\n\n", visible).strip()
    return thoughts, visible


def _strip_incomplete_suffix(text: str, marker: str) -> str:
    max_len = min(len(text), len(marker) - 1)
    for size in range(max_len, 0, -1):
        if marker.startswith(text[-size:]):
            return text[:-size]
    return text


def _parse_streaming_antml(markdown_text: str) -> tuple[list[str], str, str, bool]:
    thoughts: list[str] = []
    visible_parts: list[str] = []
    cursor = 0

    while True:
        match = re.search(r"<antml:thinking\b[^>]*>", markdown_text[cursor:], re.IGNORECASE)
        if match is None:
            visible_parts.append(
                _strip_incomplete_suffix(markdown_text[cursor:], _ANTML_THINKING_OPEN_PREFIX)
            )
            break

        start = cursor + match.start()
        end = cursor + match.end()
        visible_parts.append(markdown_text[cursor:start])

        close_idx = markdown_text.find(_ANTML_THINKING_CLOSE, end)
        if close_idx == -1:
            visible = re.sub(r"\n{3,}", "\n\n", "".join(visible_parts)).strip()
            open_thought = _strip_incomplete_suffix(
                markdown_text[end:],
                _ANTML_THINKING_CLOSE,
            )
            return thoughts, visible, open_thought, True

        thought = markdown_text[end:close_idx].strip()
        if thought:
            thoughts.append(thought)
        cursor = close_idx + len(_ANTML_THINKING_CLOSE)

    visible = re.sub(r"\n{3,}", "\n\n", "".join(visible_parts)).strip()
    return thoughts, visible, "", False


def _message_markdown(value: str, *, subdued: bool = False) -> ft.Markdown:
    chat_font = theme.FONT_SANS
    chat_fallback = list(getattr(theme, "FONT_SANS_FALLBACK", []))
    if chat_font not in chat_fallback:
        chat_fallback.insert(0, chat_font)
    em_font = getattr(theme, "FONT_EM", chat_font)
    em_fallback = list(getattr(theme, "FONT_EM_FALLBACK", chat_fallback))
    if em_font not in em_fallback:
        em_fallback.insert(0, em_font)
    primary = theme.TEXT_SECONDARY if subdued else theme.TEXT_PRIMARY
    secondary = theme.TEXT_TERTIARY
    sz = theme.FONT_SIZE
    sz_sub = sz - 2  # subdued / code size
    return ft.Markdown(
        value or " ",
        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
        selectable=True,
        code_theme=(
            ft.MarkdownCodeTheme.GRUVBOX_DARK
            if theme.is_dark()
            else ft.MarkdownCodeTheme.GRUVBOX_LIGHT
        ),
        md_style_sheet=ft.MarkdownStyleSheet(
            p_text_style=ft.TextStyle(
                font_family=chat_font,
                font_family_fallback=chat_fallback,
                size=sz_sub if subdued else sz,
                color=primary,
                height=1.5 if subdued else 1.55,
            ),
            em_text_style=ft.TextStyle(
                font_family=em_font,
                font_family_fallback=em_fallback,
                size=(sz_sub + 1) if subdued else sz + 1,
                color=secondary,
                weight=ft.FontWeight.W_400,
                italic=False,
                height=1.5 if subdued else 1.55,
            ),
            strong_text_style=ft.TextStyle(
                font_family=chat_font,
                font_family_fallback=chat_fallback,
                size=sz_sub if subdued else sz,
                color=theme.TEXT_PRIMARY,
                weight=ft.FontWeight.W_700,
                height=1.5 if subdued else 1.55,
            ),
            a_text_style=ft.TextStyle(
                font_family=chat_font,
                font_family_fallback=chat_fallback,
                size=sz_sub if subdued else sz,
                color=theme.ACCENT,
            ),
            list_bullet_text_style=ft.TextStyle(
                font_family=chat_font,
                font_family_fallback=chat_fallback,
                size=sz_sub if subdued else sz,
                color=primary,
                height=1.5 if subdued else 1.55,
            ),
            blockquote_text_style=ft.TextStyle(
                font_family=chat_font,
                font_family_fallback=chat_fallback,
                size=sz_sub if subdued else sz - 1,
                color=theme.TEXT_SECONDARY,
                height=1.5,
            ),
            blockquote_decoration=ft.BoxDecoration(
                bgcolor=theme.BG_ELEVATED,
                border=ft.border.only(left=ft.BorderSide(3, theme.ACCENT_FAINT)),
                border_radius=theme.RADIUS_MD,
            ),
            h1_text_style=ft.TextStyle(
                font_family=chat_font,
                font_family_fallback=chat_fallback,
                size=sz + 6,
                color=theme.TEXT_PRIMARY,
                weight=ft.FontWeight.W_700,
            ),
            h2_text_style=ft.TextStyle(
                font_family=chat_font,
                font_family_fallback=chat_fallback,
                size=sz + 2,
                color=theme.TEXT_PRIMARY,
                weight=ft.FontWeight.W_700,
            ),
            h3_text_style=ft.TextStyle(
                font_family=chat_font,
                font_family_fallback=chat_fallback,
                size=sz,
                color=theme.TEXT_PRIMARY,
                weight=ft.FontWeight.W_600,
            ),
        ),
        code_style_sheet=ft.MarkdownStyleSheet(
            code_text_style=ft.TextStyle(
                font_family=theme.FONT_MONO,
                font_family_fallback=getattr(theme, "FONT_MONO_FALLBACK", None),
                size=sz_sub if subdued else sz - 1,
                color=theme.TEXT_SECONDARY if not subdued else theme.TEXT_TERTIARY,
            ),
            codeblock_padding=ft.padding.symmetric(horizontal=12, vertical=10),
            codeblock_decoration=ft.BoxDecoration(
                bgcolor=theme.BG_ELEVATED,
                border=ft.border.all(1, theme.BORDER_SUBTLE),
                border_radius=theme.RADIUS_CODE,
            ),
        ),
    )

def user_bubble(
    text: str,
    on_edit: Callable | None = None,
    msg_index: int = -1,
    content_width: int | None = None,
    queued: bool = False,
    images: list | None = None,
) -> ft.Container:
    """User message: right-aligned, rounded warm box. Edit icon on hover.

    When queued=True, the bubble is rendered at reduced opacity (steering message
    waiting to be sent). Call set_queued_opacity(container, 1.0) to restore.
    ``images`` is a list of (base64_data, media_type) tuples for inline previews.
    """
    edit_btn = ft.IconButton(
        icon=ft.Icons.EDIT_OUTLINED,
        icon_color=theme.TEXT_TERTIARY,
        icon_size=13,
        tooltip="Edit & resend",
        on_click=lambda e: on_edit(msg_index, text) if on_edit else None,
        style=ft.ButtonStyle(
            shape=ft.CircleBorder(),
            padding=ft.padding.all(2),
        ),
        opacity=0,
    )

    def _show(e):
        edit_btn.opacity = 0.7
        edit_btn.update()

    def _hide(e):
        edit_btn.opacity = 0
        edit_btn.update()

    bubble_children: list[ft.Control] = []
    # Image thumbnails
    if images:
        img_row: list[ft.Control] = []
        for b64data, media_type in images:
            mime = media_type or "image/png"
            data_uri = f"data:{mime};base64,{b64data[:300000]}"
            img_row.append(
                ft.Container(
                    content=ft.Image(src=data_uri, width=160, height=120, fit="cover"),
                    width=160,
                    height=120,
                    border_radius=8,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                )
            )
        bubble_children.append(
            ft.Row(img_row, spacing=6, wrap=True, tight=True)
        )
    if text.strip():
        bubble_children.append(
            ft.Text(
                text,
                color=theme.TEXT_PRIMARY,
                size=theme.FONT_SIZE,
                selectable=True,
                no_wrap=False,
                overflow=ft.TextOverflow.VISIBLE,
                font_family=theme.FONT_SANS,
                font_family_fallback=getattr(theme, "FONT_SANS_FALLBACK", None),
            )
        )

    bubble = ft.Container(
        content=ft.Column(bubble_children, spacing=8, tight=True) if len(bubble_children) > 1 else (bubble_children[0] if bubble_children else ft.Container()),
        bgcolor=theme.BG_ELEVATED,
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        border_radius=theme.RADIUS_LG,
    )
    max_bubble_width = max(160, int((content_width or theme.MESSAGE_MAX_WIDTH) * 0.86))
    bubble_shell = ft.Container(
        content=bubble,
        width=max_bubble_width,
        alignment=ft.Alignment(1, 0),
    )

    col = ft.Column(
        [
            ft.Row(
                [ft.Container(expand=True), bubble_shell],
                spacing=0,
            ),
            ft.Row(
                [ft.Container(expand=True), edit_btn],
                spacing=0,
            ) if on_edit else ft.Container(height=0),
        ],
        spacing=2,
        tight=True,
    )

    if on_edit:
        wrapper = ft.GestureDetector(content=col, on_enter=_show, on_exit=_hide)
    else:
        wrapper = col

    outer = ft.Container(
        content=wrapper,
        width=content_width or theme.MESSAGE_MAX_WIDTH,
        alignment=ft.Alignment(1, 0),
        margin=ft.margin.only(top=16, bottom=8),
        opacity=0.4 if queued else 1.0,
    )
    return outer


def assistant_message(
    markdown_text: str,
    on_retry: Callable | None = None,
    msg_index: int = -1,
) -> ft.Container:
    """Assistant: full-width markdown with hover retry button."""
    thoughts, visible_markdown = _extract_antml_thinking(markdown_text or "")
    md = _message_markdown(visible_markdown or " ")
    retry_btn = ft.IconButton(
        icon=ft.Icons.REFRESH,
        icon_color=theme.TEXT_TERTIARY,
        icon_size=13,
        tooltip="Retry from here",
        on_click=lambda e: on_retry(msg_index) if on_retry else None,
        style=ft.ButtonStyle(
            shape=ft.CircleBorder(),
            padding=ft.padding.all(2),
        ),
        opacity=0,
    )

    def _show(e):
        retry_btn.opacity = 0.7
        retry_btn.update()

    def _hide(e):
        retry_btn.opacity = 0
        retry_btn.update()

    body_controls: list[ft.Control] = [_thinking_panel(thought) for thought in thoughts]
    if visible_markdown or not thoughts:
        body_controls.append(md)
    body_controls.append(retry_btn if on_retry else ft.Container(height=0))

    col = ft.Column(body_controls, spacing=2)

    if on_retry:
        wrapper = ft.GestureDetector(content=col, on_enter=_show, on_exit=_hide)
    else:
        wrapper = col

    return ft.Container(
        content=wrapper,
        margin=ft.margin.only(top=12, bottom=8, right=40),
        padding=ft.padding.only(left=4),
    )


def _make_collapsible_panel(
    header_row: ft.Row,
    body_content: ft.Control,
    *,
    bg: str,
    border_color: str,
    margin_top: int = 6,
    margin_bottom: int = 2,
    margin_right: int = 40,
    initially_open: bool = False,
) -> ft.Container:
    """Create a collapsible panel: header always visible, body toggled on click."""
    body_wrapper = ft.Container(
        content=ft.Column([ft.Container(height=6), body_content], spacing=0, tight=True),
        visible=initially_open,
    )
    chevron = ft.Icon(
        ft.Icons.EXPAND_MORE if initially_open else ft.Icons.CHEVRON_RIGHT,
        color=theme.TEXT_TERTIARY,
        size=14,
    )

    def toggle(_e):
        body_wrapper.visible = not body_wrapper.visible
        chevron.name = ft.Icons.EXPAND_MORE if body_wrapper.visible else ft.Icons.CHEVRON_RIGHT
        outer.update()

    clickable_header = ft.Container(
        content=ft.Row(
            [chevron, header_row],
            spacing=4,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        on_click=toggle,
        ink=False,
    )

    outer = ft.Container(
        content=ft.Column([clickable_header, body_wrapper], spacing=0, tight=True),
        bgcolor=bg,
        border=ft.border.all(1, border_color),
        border_radius=theme.RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=14, vertical=10),
        margin=ft.margin.only(top=margin_top, bottom=margin_bottom, right=margin_right),
    )
    return outer


def _thinking_panel(
    thought: str,
    *,
    initially_open: bool = False,
    title: str = "Thinking",
) -> ft.Container:
    header = ft.Row(
        [
            ft.Icon(ft.Icons.PSYCHOLOGY_ALT_OUTLINED, color=theme.ACCENT, size=13),
            ft.Text(
                title,
                color=theme.ACCENT,
                size=12,
                weight=ft.FontWeight.W_600,
            ),
        ],
        spacing=6,
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    return _make_collapsible_panel(
        header,
        _message_markdown(thought or "…", subdued=True),
        bg=theme.BG_ELEVATED,
        border_color=theme.BORDER_FAINT,
        margin_top=0,
        margin_bottom=8,
        margin_right=0,
        initially_open=initially_open,
    )


def streaming_assistant_message(markdown_text: str) -> ft.Container:
    thoughts, visible_markdown, open_thought, thinking_open = _parse_streaming_antml(markdown_text or "")
    body_controls: list[ft.Control] = [_thinking_panel(thought) for thought in thoughts]
    if thinking_open:
        body_controls.append(
            _thinking_panel(
                open_thought,
                initially_open=True,
                title="Thinking…",
            )
        )
    if visible_markdown:
        body_controls.append(_message_markdown(visible_markdown))
    elif not body_controls:
        body_controls.append(_message_markdown("…"))

    return ft.Container(
        content=ft.Column(body_controls, spacing=2),
        margin=ft.margin.only(top=12, bottom=8, right=40),
        padding=ft.padding.only(left=4),
    )


def tool_call_panel(name: str, input_dict: dict, *, nested: bool = False) -> ft.Container:
    return _tool_log_entry(
        name=name,
        input_dict=input_dict,
        result_content=None,
        is_error=False,
        nested=nested,
    )


def _tool_call_summary(name: str, input_dict: dict) -> str:
    """Return a short one-line summary string for the collapsed tool call header."""
    def squish(text: str) -> str:
        return " ".join((text or "").split())

    n = name.lower()
    if n in ("read", "write") and "file_path" in input_dict:
        return squish(input_dict["file_path"])
    if n == "edit" and "file_path" in input_dict:
        return squish(input_dict["file_path"])
    if n == "bash" and "command" in input_dict:
        cmd = squish(input_dict["command"])
        return cmd if len(cmd) <= 80 else cmd[:77] + "…"
    if n in ("glob",) and "pattern" in input_dict:
        return squish(input_dict["pattern"])
    if n in ("grep",) and "pattern" in input_dict:
        return squish(input_dict["pattern"])
    if n == "agent" and "description" in input_dict:
        return squish(input_dict["description"])
    if "description" in input_dict:
        d = squish(input_dict["description"])
        return d if len(d) <= 80 else d[:77] + "…"
    # Fallback: first string value
    for v in input_dict.values():
        if isinstance(v, str) and v:
            v = squish(v)
            return v if len(v) <= 60 else v[:57] + "…"
    return ""


def tool_result_panel(content: str, is_error: bool = False) -> ft.Container:
    """Standalone result panel (fallback when no preceding tool_call found)."""
    return tool_combined_panel("tool", {}, content, is_error)


def _result_summary(name: str, content: str, is_error: bool) -> str:
    """One-line result summary for the collapsed header."""
    if is_error:
        first = content.strip().splitlines()[0] if content.strip() else "error"
        return first[:60]
    n = name.lower()
    if n == "bash":
        # Extract exit code
        for line in content.splitlines():
            if "exit_code" in line.lower() or "exit code" in line.lower():
                return line.strip()[:60]
        lines = content.strip().splitlines()
        return f"{len(lines)} lines" if lines else "done"
    if n == "read":
        lines = content.strip().splitlines()
        return f"{len(lines)} lines"
    if n == "write":
        return content.strip().splitlines()[0][:60] if content.strip() else "done"
    if n in ("glob", "grep"):
        lines = content.strip().splitlines()
        return f"{len(lines)} results" if len(lines) > 1 else (lines[0][:60] if lines else "no results")
    if n == "edit":
        return "applied" if not is_error else content.splitlines()[0][:60]
    # Generic
    first = content.strip().splitlines()[0] if content.strip() else "done"
    return first[:60] if len(first) <= 60 else first[:57] + "…"


def tool_combined_panel(
    name: str, input_dict: dict, result_content: str, is_error: bool = False, *, nested: bool = False,
) -> ft.Container:
    return _tool_log_entry(
        name=name,
        input_dict=input_dict,
        result_content=result_content,
        is_error=is_error,
        nested=nested,
    )


def tool_stack_panel(
    entries: list[tuple[str, dict, str | None, bool]],
    *,
    nested: bool = False,
) -> ft.Container:
    if not entries:
        return ft.Container(height=0)
    return ft.Container(
        content=ft.Column(
            [
                _tool_log_entry(
                    name=name,
                    input_dict=input_dict,
                    result_content=result_content,
                    is_error=is_error,
                    nested=nested,
                    index=index,
                )
                for index, (name, input_dict, result_content, is_error) in enumerate(entries, start=1)
            ],
            spacing=0,
            tight=True,
        ),
        margin=ft.margin.only(top=6, bottom=6),
    )


def tool_turn_panel(
    entries: list[tuple[str, dict, str | None, bool]],
) -> ft.Container:
    return tool_stack_panel(entries)


def _tool_inline_body(
    content: ft.Control,
    *,
    nested: bool = False,
    initially_open: bool = False,
) -> tuple[ft.Container, ft.Icon]:
    body_wrapper = ft.Container(
        content=ft.Container(
            content=content,
            border=ft.border.only(left=ft.BorderSide(1, theme.BORDER_FAINT)),
            padding=ft.padding.only(left=12, top=2, bottom=2),
            margin=ft.margin.only(left=18, top=4),
        ),
        visible=initially_open,
    )
    chevron = ft.Icon(
        ft.Icons.EXPAND_MORE if initially_open else ft.Icons.CHEVRON_RIGHT,
        color=theme.TEXT_TERTIARY,
        size=14,
    )
    return body_wrapper, chevron


def _tool_log_entry(
    *,
    name: str,
    input_dict: dict,
    result_content: str | None,
    is_error: bool,
    nested: bool = False,
    index: int | None = None,
) -> ft.Container:
    try:
        input_body = json.dumps(input_dict, indent=2, ensure_ascii=False)
    except Exception:
        input_body = str(input_dict)
    if len(input_body) > 1200:
        input_body = input_body[:1200] + "\n…"

    result_body = result_content or ""
    if len(result_body) > 2500:
        result_body = result_body[:2500] + f"\n…(+{len(result_body) - 2500} chars)"

    prefix = f"{index} {name.lower()}" if index is not None else name.lower()
    summary = _tool_call_summary(name, input_dict)
    status_text = (
        "running…"
        if result_content is None
        else _result_summary(name, result_content, is_error)
    )
    status_color = (
        theme.TEXT_TERTIARY
        if result_content is None
        else (theme.ERROR if is_error else theme.SUCCESS)
    )

    detail_children: list[ft.Control] = [
        ft.Text("Input", color=theme.TEXT_TERTIARY, size=10, weight=ft.FontWeight.W_600),
        ft.Text(
            input_body or "{}",
            font_family=theme.FONT_MONO,
            size=11,
            color=theme.TEXT_SECONDARY,
            selectable=True,
        ),
    ]
    if result_content is not None:
        detail_children.extend(
            [
                ft.Container(height=6),
                ft.Text(
                    "Result",
                    color=status_color,
                    size=10,
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text(
                    result_body or "done",
                    font_family=theme.FONT_MONO,
                    size=11,
                    color=theme.ERROR if is_error else theme.TEXT_SECONDARY,
                    selectable=True,
                ),
            ]
        )

    body_wrapper, chevron = _tool_inline_body(
        ft.Column(detail_children, spacing=2, tight=True),
        nested=nested,
        initially_open=False,
    )

    def toggle(_e):
        body_wrapper.visible = not body_wrapper.visible
        chevron.name = ft.Icons.EXPAND_MORE if body_wrapper.visible else ft.Icons.CHEVRON_RIGHT
        outer.update()

    header = ft.Container(
        content=ft.Row(
            [
                chevron,
                ft.Text(
                    prefix,
                    color=theme.ACCENT,
                    size=12,
                    weight=ft.FontWeight.W_700,
                    font_family=theme.FONT_MONO,
                ),
                ft.Text(
                    summary,
                    color=theme.TEXT_SECONDARY,
                    size=12,
                    font_family=theme.FONT_MONO,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                    expand=True,
                ),
                ft.Text(
                    status_text,
                    color=status_color,
                    size=11,
                    font_family=theme.FONT_MONO,
                    no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ],
            spacing=6,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        on_click=toggle,
        padding=ft.padding.only(top=2, bottom=2),
        ink=False,
    )

    outer = ft.Container(
        content=ft.Column([header, body_wrapper], spacing=0, tight=True),
        margin=ft.margin.only(top=2, bottom=2, right=0 if nested else 40),
    )
    return outer


def thinking_indicator() -> ft.Container:
    """Animated thinking indicator shown during streaming."""
    return ft.Container(
        content=ft.Row(
            [
                ft.Text(
                    "+",
                    color=theme.ACCENT,
                    size=14,
                    weight=ft.FontWeight.W_700,
                ),
                ft.Text(
                    "Thinking…",
                    color=theme.ACCENT,
                    size=13,
                    italic=True,
                ),
            ],
            spacing=6,
            tight=True,
        ),
        padding=ft.padding.only(left=8, top=8, bottom=8),
        animate_opacity=200,
    )


def system_note(text: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(
            text,
            color=theme.TEXT_TERTIARY,
            size=12,
            italic=True,
            text_align=ft.TextAlign.CENTER,
        ),
        padding=ft.padding.symmetric(vertical=10),
        alignment=ft.Alignment(0, 0),
    )


def error_panel(text: str) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.WARNING_AMBER, color=theme.ERROR, size=16),
                ft.Text(
                    text,
                    color=theme.ERROR,
                    selectable=True,
                    expand=True,
                    size=13,
                ),
            ],
            spacing=10,
        ),
        bgcolor="#3a1f1f",
        border=ft.border.all(1, theme.ERROR),
        border_radius=theme.RADIUS_MD,
        padding=ft.padding.symmetric(horizontal=14, vertical=12),
        margin=ft.margin.symmetric(vertical=8),
    )


def welcome_screen(
    cwd: str = "",
    on_change_cwd: Callable | None = None,
    wordmark: ft.Control | None = None,
    subtitle: str = "",
    accent_color: str = "",
) -> ft.Container:
    """Empty-state — OpenH wordmark + workspace selector."""
    from pathlib import Path

    # Shorten cwd for display
    display_cwd = cwd
    home = str(Path.home())
    if display_cwd.startswith(home):
        display_cwd = "~" + display_cwd[len(home):]

    cwd_row = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.FOLDER_OUTLINED, color=theme.TEXT_TERTIARY, size=14),
                ft.Text(
                    display_cwd,
                    color=theme.TEXT_SECONDARY,
                    size=12,
                    font_family=theme.FONT_MONO,
                ),
                ft.TextButton(
                    "Change",
                    style=ft.ButtonStyle(
                        color=accent_color or theme.ACCENT,
                        padding=ft.padding.symmetric(horizontal=8, vertical=0),
                    ),
                    on_click=lambda e: on_change_cwd() if on_change_cwd else None,
                ),
            ],
            spacing=6,
            tight=True,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.only(top=16),
    ) if cwd else ft.Container()

    sub_text = subtitle or "What can I help you with?"

    if theme.is_fnd():
        dark = theme.is_dark()
        workspace = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        ft.Icons.FOLDER_OUTLINED,
                        color=theme.TEXT_TERTIARY,
                        size=14,
                    ),
                    ft.Text(
                        display_cwd,
                        color=theme.TEXT_SECONDARY,
                        size=12,
                        font_family=theme.FONT_MONO,
                        expand=True,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    ),
                    ft.TextButton(
                        "Change",
                        style=ft.ButtonStyle(
                            color=accent_color or theme.ACCENT,
                            padding=ft.padding.symmetric(horizontal=6, vertical=0),
                        ),
                        on_click=lambda e: on_change_cwd() if on_change_cwd else None,
                    ),
                ],
                spacing=8,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=18, vertical=12),
            border_radius=theme.RADIUS_LG,
            border=ft.border.all(1, theme.BORDER_FAINT),
            bgcolor=theme.BG_ELEVATED,
        ) if cwd else ft.Container()

        return ft.Container(
            content=ft.Container(
                width=760,
                content=ft.Column(
                    [
                        wordmark or (
                            ft.Text(
                                "FRUITS & DESSERT",
                                color=accent_color or theme.ACCENT,
                                size=38,
                                weight=ft.FontWeight.W_700,
                                text_align=ft.TextAlign.CENTER,
                                font_family=theme.FONT_SANS,
                            ) if dark else ft.Text(
                                "Fruits & Dessert",
                                color=accent_color or theme.ACCENT,
                                size=44,
                                weight=ft.FontWeight.W_600,
                                text_align=ft.TextAlign.CENTER,
                                font_family=theme.FONT_EM,
                                italic=True,
                            )
                        ),
                        ft.Text(
                            sub_text,
                            color=theme.TEXT_SECONDARY,
                            size=12 if dark else 13,
                            text_align=ft.TextAlign.CENTER,
                            font_family=theme.FONT_MONO,
                        ),
                        ft.Container(height=6),
                        workspace,
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    alignment=ft.MainAxisAlignment.CENTER,
                    spacing=10,
                ),
            ),
            alignment=ft.Alignment(0, -0.08),
            padding=ft.padding.only(left=32, right=32, top=104, bottom=42),
            expand=True,
        )

    children: list[ft.Control] = [
        wordmark or ft.Text(
            "O p e n H",
            color=accent_color or theme.ACCENT,
            size=32,
            weight=ft.FontWeight.W_300,
            text_align=ft.TextAlign.CENTER,
            font_family=theme.FONT_SANS,
        ),
        ft.Text(
            sub_text,
            color=theme.TEXT_TERTIARY,
            size=14,
            text_align=ft.TextAlign.CENTER,
        ),
        cwd_row,
    ]

    return ft.Container(
        content=ft.Column(
            children,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            tight=True,
        ),
        alignment=ft.Alignment(0, 0),
        padding=ft.padding.only(top=120, bottom=40),
        expand=True,
    )


# ============================================================================
#  Input area
# ============================================================================

def _pill_button(
    label: str,
    icon: str | None,
    on_click: Callable,
    tooltip: str = "",
    color: str | None = None,
) -> ft.Container:
    """Small pill-shaped button with optional leading icon and trailing chevron."""
    children: list[ft.Control] = []
    if icon is not None:
        children.append(
            ft.Icon(icon, color=color or theme.TEXT_SECONDARY, size=14)
        )
    children.append(
        ft.Text(
            label,
            color=color or theme.TEXT_SECONDARY,
            size=12,
        )
    )
    children.append(
        ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, color=theme.TEXT_TERTIARY, size=14)
    )
    return ft.Container(
        content=ft.Row(children, spacing=4, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.padding.symmetric(horizontal=10, vertical=6),
        border_radius=theme.RADIUS_PILL,
        ink=True,
        on_click=lambda e: on_click(),
        tooltip=tooltip or label,
    )


def model_dropdown(
    provider_name: str,
    model: str,
    on_pick: Callable[[str, str], None],  # (provider, model) -> None
) -> ft.PopupMenuButton:
    """Real dropdown with grouped model options. Click → menu → pick one."""
    from ..settings import ANTHROPIC_MODELS, GEMINI_MODELS, OPENAI_MODELS

    def header(label: str) -> ft.PopupMenuItem:
        return ft.PopupMenuItem(
            content=ft.Text(
                label,
                color=theme.TEXT_TERTIARY,
                size=10,
                weight=ft.FontWeight.W_700,
                font_family=theme.FONT_MONO,
            ),
            disabled=True,
            height=28,
        )

    def choice(provider: str, m: str, active: bool) -> ft.PopupMenuItem:
        return ft.PopupMenuItem(
            content=ft.Row(
                [
                    ft.Container(
                        width=10,
                        height=10,
                        border_radius=5,
                        bgcolor=theme.ACCENT if active else "transparent",
                    ),
                    ft.Text(
                        m,
                        color=theme.TEXT_PRIMARY,
                        size=13,
                        weight=ft.FontWeight.W_500 if active else ft.FontWeight.W_400,
                    ),
                ],
                spacing=10,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=lambda e, pp=provider, mm=m: on_pick(pp, mm),
        )

    items: list[ft.PopupMenuItem] = []
    items.append(header("OPENAI"))
    for m in OPENAI_MODELS:
        items.append(choice("openai", m, provider_name == "openai" and m == model))
    items.append(ft.PopupMenuItem())  # divider
    items.append(header("ANTHROPIC"))
    for m in ANTHROPIC_MODELS:
        items.append(choice("anthropic", m, provider_name == "anthropic" and m == model))
    items.append(ft.PopupMenuItem())  # divider
    items.append(header("GEMINI"))
    for m in GEMINI_MODELS:
        items.append(choice("gemini", m, provider_name == "gemini" and m == model))

    return ft.PopupMenuButton(
        content=ft.Container(
            content=ft.Row(
                [
                    ft.Text(
                        provider_name,
                        color=theme.TEXT_TERTIARY,
                        size=12,
                    ),
                    ft.Text(
                        model,
                        color=theme.TEXT_PRIMARY,
                        size=12,
                        weight=ft.FontWeight.W_500,
                    ),
                    ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, color=theme.TEXT_TERTIARY, size=14),
                ],
                spacing=6,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=6),
            border_radius=theme.RADIUS_PILL,
        ),
        bgcolor=theme.BG_ELEVATED,
        menu_position=ft.PopupMenuPosition.OVER,
        size_constraints=ft.BoxConstraints(max_width=380),
        menu_padding=0,
        items=items,
        tooltip="Switch model",
    )


def input_area(
    input_field: ft.TextField,
    on_send: Callable,
    on_attach: Callable,
    on_toggle_permissions: Callable,
    on_pick_model: Callable[[str, str], None],
    provider_name: str,
    model: str,
    skip_permissions: bool,
    busy: bool = False,
    on_stop: Callable | None = None,
    content_width: int | None = None,
    attachments: list[tuple[int, str]] | None = None,
    queued_inputs: list[str] | None = None,
    on_remove_queued_input: Callable[[int], None] | None = None,
    on_remove_attachment: Callable[[int], None] | None = None,
) -> ft.Container:
    """Large rounded input box — Claude.app style.

    Layout inside the box:
      ┌─────────────────────────────────────────────┐
      │ [text input, multi-line]                    │
      │                                             │
      │ [+]  [⚠ perms v]        [model v]  [↑]      │
      └─────────────────────────────────────────────┘
    """
    is_fnd = theme.is_fnd()
    dark_fnd = is_fnd and theme.is_dark()

    attach_btn = ft.IconButton(
        icon=ft.Icons.ADD,
        icon_color=theme.TEXT_SECONDARY,
        icon_size=20,
        tooltip="Attach file",
        on_click=lambda e: on_attach(),
        style=ft.ButtonStyle(
            shape=ft.CircleBorder(),
            padding=ft.padding.all(6),
            overlay_color=theme.BG_HOVER,
        ),
    )

    perms_label = "skip perms" if skip_permissions else "perms on"
    perms_color = theme.WARN if skip_permissions else theme.TEXT_SECONDARY
    perms_btn = _pill_button(
        label=perms_label,
        icon=ft.Icons.WARNING_AMBER if skip_permissions else ft.Icons.SHIELD_OUTLINED,
        on_click=on_toggle_permissions,
        tooltip="Toggle permission mode",
        color=perms_color,
    )

    model_btn = model_dropdown(
        provider_name=provider_name,
        model=model,
        on_pick=on_pick_model,
    )

    right_buttons: list[ft.Control] = [model_btn, ft.Container(width=10)]

    send_btn = ft.Container(
        content=ft.Icon(ft.Icons.ARROW_UPWARD, color=theme.TEXT_ON_ACCENT, size=18),
        width=36,
        height=36,
        alignment=ft.Alignment(0, 0),
        bgcolor=theme.ACCENT,
        border_radius=12,
        ink=True,
        on_click=lambda e: on_send(),
        tooltip="Send / queue steering (Enter)",
    )

    has_text = bool((input_field.value or "").strip())
    stop_btn = ft.Container(
        content=ft.Icon(ft.Icons.STOP_ROUNDED, color=theme.TEXT_SECONDARY, size=14),
        width=36,
        height=36,
        alignment=ft.Alignment(0, 0),
        border=ft.border.all(1, theme.BORDER_SUBTLE),
        border_radius=12,
        ink=True,
        on_click=lambda e: on_stop(),
        tooltip="Stop generation (Esc)",
    )

    if busy and on_stop:
        if has_text:
            steering_send = ft.Container(
                content=ft.Icon(ft.Icons.ARROW_UPWARD, color=theme.TEXT_ON_ACCENT, size=18),
                width=36,
                height=36,
                alignment=ft.Alignment(0, 0),
                bgcolor=theme.ACCENT,
                border_radius=12,
                ink=True,
                on_click=lambda e: on_send(),
                tooltip="Send / queue steering (Enter)",
            )
            right_buttons.extend([steering_send, stop_btn])
        else:
            right_buttons.append(stop_btn)
    else:
        right_buttons.append(send_btn)

    bottom_row = ft.Row(
        [
            attach_btn,
            ft.Container(width=4),
            perms_btn,
            ft.Container(expand=True),
            *right_buttons,
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # Attachment chips row (above text input)
    box_children: list[ft.Control] = []
    if queued_inputs:
        queue_chips: list[ft.Control] = []
        for idx, value in enumerate(queued_inputs):
            preview = (value or "").strip()
            if len(preview) > 48:
                preview = preview[:48].rstrip() + "..."
            chip_children: list[ft.Control] = [
                ft.Text(
                    preview or "(queued)",
                    color=theme.TEXT_SECONDARY,
                    size=12,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ]
            if on_remove_queued_input is not None:
                chip_children.append(
                    ft.IconButton(
                        icon=ft.Icons.CLOSE,
                        icon_color=theme.TEXT_TERTIARY,
                        icon_size=12,
                        tooltip="Remove queued input",
                        on_click=lambda e, i=idx: on_remove_queued_input(i),
                        style=ft.ButtonStyle(
                            shape=ft.CircleBorder(),
                            padding=ft.padding.all(0),
                        ),
                    )
                )
            queue_chips.append(
                ft.Container(
                    content=ft.Row(
                        chip_children,
                        spacing=6,
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=theme.ACCENT_FAINT,
                    border_radius=12,
                    padding=ft.padding.only(left=10, right=6, top=5, bottom=5),
                )
            )
        box_children.append(
            ft.Row(queue_chips, spacing=6, tight=True, wrap=True)
        )
        box_children.append(ft.Container(height=6))

    if attachments:
        import base64 as _b64mod
        chips: list[ft.Control] = []
        for idx, label, b64data in attachments:
            is_image = "Image" in label
            chip_children: list[ft.Control] = []
            # Thumbnail for images
            if is_image and b64data:
                # data URI for inline image thumbnail
                data_uri = f"data:image/png;base64,{b64data[:200000]}"
                chip_children.append(
                    ft.Container(
                        content=ft.Image(
                            src=data_uri,
                            width=32,
                            height=32,
                            fit="cover",
                        ),
                        width=32,
                        height=32,
                        border_radius=4,
                        clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    )
                )
            else:
                chip_children.append(
                    ft.Icon(ft.Icons.ATTACH_FILE, color=theme.TEXT_TERTIARY, size=14)
                )
            chip_children.append(
                ft.Text(
                    "image" if is_image else label,
                    color=theme.TEXT_SECONDARY,
                    size=12,
                )
            )
            chip_children.append(
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_color=theme.TEXT_TERTIARY,
                    icon_size=12,
                    tooltip="Remove",
                    on_click=lambda e, i=idx: on_remove_attachment(i) if on_remove_attachment else None,
                    style=ft.ButtonStyle(
                        shape=ft.CircleBorder(),
                        padding=ft.padding.all(0),
                    ),
                )
            )
            chips.append(
                ft.Container(
                    content=ft.Row(
                        chip_children,
                        spacing=6,
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=theme.BG_ELEVATED,
                    border=ft.border.all(1, theme.BORDER_SUBTLE),
                    border_radius=theme.RADIUS_SM,
                    padding=ft.padding.only(left=4, right=2, top=2, bottom=2),
                )
            )
        box_children.append(
            ft.Row(chips, spacing=6, tight=True, wrap=True)
        )
        box_children.append(ft.Container(height=6))

    # Wrap input_field in a Row so its expand=True works horizontally, not vertically
    box_children.extend([
        ft.Row([input_field], spacing=0, tight=True),
        ft.Container(height=4),
        bottom_row,
    ])

    box = ft.Container(
        content=ft.Column(
            box_children,
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
        bgcolor=theme.BG_ELEVATED if is_fnd else theme.BG_DEEPEST,
        border=ft.border.all(1, theme.BORDER_SUBTLE),
        border_radius=24 if is_fnd else theme.RADIUS_LG,
        padding=ft.padding.only(left=14, right=10, top=10, bottom=10),
    )

    return ft.Container(
        content=ft.Container(
            content=box,
            width=content_width or theme.MESSAGE_MAX_WIDTH,
        ),
        alignment=ft.Alignment(0, 0),
        padding=ft.padding.only(
            left=theme.PADDING_GUTTER,
            right=theme.PADDING_GUTTER,
            top=8,
            bottom=12,
        ),
    )
