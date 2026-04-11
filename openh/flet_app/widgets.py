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
from typing import Callable

import flet as ft

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
    show_hidden: bool = False,
    user_label: str = "openh",
    width: int = theme.SIDEBAR_WIDTH,
) -> ft.Container:
    """Left navigation rail with [+ New chat], grouped session list."""

    new_chat_btn = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.EDIT_SQUARE, color=theme.TEXT_PRIMARY, size=16),
                ft.Text(
                    "New chat",
                    color=theme.TEXT_PRIMARY,
                    size=13,
                    weight=ft.FontWeight.W_500,
                ),
            ],
            spacing=10,
            tight=True,
        ),
        padding=ft.padding.symmetric(horizontal=12, vertical=9),
        bgcolor=theme.BG_PAGE,
        border=ft.border.all(1, theme.BORDER_SUBTLE),
        border_radius=theme.RADIUS_MD,
        on_click=lambda e: on_new_chat(),
        ink=True,
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

    return ft.Container(
        width=width,
        bgcolor=theme.BG_SIDEBAR,
        border=ft.border.only(right=ft.BorderSide(1, theme.BORDER_FAINT)),
        content=ft.Column(
            [
                ft.Container(content=new_chat_btn, padding=ft.padding.all(12)),
                ft.Container(
                    content=ft.Column(
                        body_children,
                        spacing=0,
                        tight=False,
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    expand=True,
                ),
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
    busy_note: str = "",
) -> ft.Container:
    """Conversation title bar — claude.app style with sidebar toggle on the left."""
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
    )

    note_text = ft.Text(
        busy_note,
        color=theme.ACCENT,
        size=11,
        italic=True,
    ) if busy_note else ft.Container()

    return ft.Container(
        height=theme.TOP_BAR_HEIGHT,
        bgcolor=theme.BG_PAGE,
        content=ft.Row(
            [
                toggle_btn,
                ft.Container(width=4),
                title_widget,
                ft.Container(expand=True),
                note_text,
                ft.Container(width=8),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.ARTICLE_OUTLINED, color=theme.TEXT_TERTIARY, size=13),
                            ft.Text(
                                prompt_label or "default",
                                color=theme.TEXT_TERTIARY,
                                size=11,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                        ],
                        spacing=4,
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    padding=ft.padding.symmetric(horizontal=8, vertical=4),
                    border_radius=theme.RADIUS_PILL,
                    border=ft.border.all(1, theme.BORDER_FAINT),
                    on_click=lambda e: on_edit_prompt() if on_edit_prompt else None,
                    ink=True,
                    tooltip="Edit session prompt",
                ) if on_edit_prompt else ft.Container(),
                ft.Container(width=4),
                theme_btn,
                settings_btn,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.symmetric(horizontal=14),
        border=ft.border.only(bottom=ft.BorderSide(1, theme.BORDER_FAINT)),
    )


def _estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    """Rough USD cost estimate based on published pricing (per 1M tokens)."""
    # Pricing: (input $/M, output $/M)
    pricing = {
        # Anthropic
        "claude-opus-4-6":    (15.0, 75.0),
        "claude-opus-4":      (15.0, 75.0),
        "claude-sonnet-4-6":  (3.0, 15.0),
        "claude-sonnet-4-5":  (3.0, 15.0),
        "claude-sonnet-4":    (3.0, 15.0),
        "claude-haiku-4-5":   (0.80, 4.0),
        "claude-haiku-4":     (0.80, 4.0),
        # Gemini
        "gemini-3.1-pro-preview": (1.25, 10.0),
        "gemini-2.5-pro":     (1.25, 10.0),
        "gemini-2.5-flash":   (0.15, 0.60),
        "gemini-2.0-flash":   (0.10, 0.40),
        "gemini-2.0-flash-exp": (0.0, 0.0),
    }
    in_price, out_price = pricing.get(model, (3.0, 15.0))
    return (in_tokens * in_price + out_tokens * out_price) / 1_000_000


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
    model: str = "",
    context_tokens: int = 0,
    context_limit: int = 200_000,
) -> ft.Container:
    """Thin status strip — cwd + token counts + cost estimate + context usage."""
    cost = _estimate_cost(model, in_tokens, out_tokens)
    cost_str = _format_cost(cost)

    token_label = f"in {in_tokens:,} · out {out_tokens:,}"

    right_parts = [
        ft.Text(
            token_label,
            color=theme.TEXT_TERTIARY,
            size=11,
            font_family=theme.FONT_MONO,
        ),
        ft.Text(
            cost_str,
            color=theme.ACCENT if cost > 0.01 else theme.TEXT_TERTIARY,
            size=11,
            font_family=theme.FONT_MONO,
        ),
    ]

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

def user_bubble(
    text: str,
    on_edit: Callable | None = None,
    msg_index: int = -1,
) -> ft.Container:
    """User message: right-aligned, rounded warm box. Edit icon on hover."""
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

    bubble = ft.Container(
        content=ft.Text(
            text,
            color=theme.TEXT_PRIMARY,
            size=15,
            selectable=True,
        ),
        bgcolor=theme.BG_ELEVATED,
        padding=ft.padding.symmetric(horizontal=16, vertical=12),
        border_radius=theme.RADIUS_LG,
    )

    col = ft.Column(
        [
            ft.Row(
                [ft.Container(expand=True), bubble],
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

    return ft.Container(
        content=wrapper,
        margin=ft.margin.only(top=16, bottom=8, left=80),
    )


def assistant_message(
    markdown_text: str,
    on_retry: Callable | None = None,
    msg_index: int = -1,
) -> ft.Container:
    """Assistant: full-width markdown with hover retry button."""
    md = ft.Markdown(
        markdown_text or " ",
        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
        selectable=True,
        code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK,
        code_style_sheet=ft.MarkdownStyleSheet(
            code_text_style=ft.TextStyle(
                font_family=theme.FONT_MONO,
                size=13,
                color=theme.TEXT_PRIMARY,
            ),
            p_text_style=ft.TextStyle(
                font_family=theme.FONT_SANS,
                size=15,
                color=theme.TEXT_PRIMARY,
                height=1.55,
            ),
            h1_text_style=ft.TextStyle(
                font_family=theme.FONT_SANS,
                size=22,
                color=theme.TEXT_PRIMARY,
                weight=ft.FontWeight.W_700,
            ),
            h2_text_style=ft.TextStyle(
                font_family=theme.FONT_SANS,
                size=18,
                color=theme.TEXT_PRIMARY,
                weight=ft.FontWeight.W_700,
            ),
            h3_text_style=ft.TextStyle(
                font_family=theme.FONT_SANS,
                size=16,
                color=theme.TEXT_PRIMARY,
                weight=ft.FontWeight.W_600,
            ),
        ),
    )
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

    col = ft.Column(
        [
            md,
            retry_btn if on_retry else ft.Container(height=0),
        ],
        spacing=2,
    )

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
        margin=ft.margin.only(top=margin_top, bottom=margin_bottom, right=40),
    )
    return outer


def tool_call_panel(name: str, input_dict: dict) -> ft.Container:
    try:
        body = json.dumps(input_dict, indent=2, ensure_ascii=False)
    except Exception:
        body = str(input_dict)
    if len(body) > 2000:
        body = body[:2000] + "\n…"

    # Build a one-line summary for the collapsed header
    summary = _tool_call_summary(name, input_dict)

    header = ft.Row(
        [
            ft.Container(
                width=6,
                height=6,
                border_radius=3,
                bgcolor=theme.ACCENT,
            ),
            ft.Text(
                name,
                color=theme.ACCENT,
                size=12,
                weight=ft.FontWeight.W_700,
                font_family=theme.FONT_MONO,
            ),
            ft.Text(
                summary,
                color=theme.TEXT_TERTIARY,
                size=11,
                font_family=theme.FONT_MONO,
                no_wrap=True,
                overflow=ft.TextOverflow.ELLIPSIS,
                expand=True,
            ),
        ],
        spacing=8,
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    body_text = ft.Text(
        body,
        font_family=theme.FONT_MONO,
        size=11,
        color=theme.TEXT_SECONDARY,
        selectable=True,
    )

    return _make_collapsible_panel(
        header, body_text,
        bg=theme.TOOL_CALL_BG,
        border_color=theme.TOOL_CALL_BORDER,
        margin_top=6, margin_bottom=2,
        initially_open=False,
    )


def _tool_call_summary(name: str, input_dict: dict) -> str:
    """Return a short one-line summary string for the collapsed tool call header."""
    n = name.lower()
    if n in ("read", "write") and "file_path" in input_dict:
        return input_dict["file_path"]
    if n == "edit" and "file_path" in input_dict:
        return input_dict["file_path"]
    if n == "bash" and "command" in input_dict:
        cmd = input_dict["command"]
        return cmd if len(cmd) <= 80 else cmd[:77] + "…"
    if n in ("glob",) and "pattern" in input_dict:
        return input_dict["pattern"]
    if n in ("grep",) and "pattern" in input_dict:
        return input_dict["pattern"]
    if n == "agent" and "description" in input_dict:
        return input_dict["description"]
    if "description" in input_dict:
        d = input_dict["description"]
        return d if len(d) <= 80 else d[:77] + "…"
    # Fallback: first string value
    for v in input_dict.values():
        if isinstance(v, str) and v:
            return v if len(v) <= 60 else v[:57] + "…"
    return ""


def tool_result_panel(content: str, is_error: bool = False) -> ft.Container:
    if len(content) > 4000:
        content = content[:4000] + f"\n…(+{len(content) - 4000} chars)"

    icon = ft.Icons.ERROR_OUTLINE if is_error else ft.Icons.CHECK_CIRCLE_OUTLINE
    header_color = theme.ERROR if is_error else theme.SUCCESS
    label = "error" if is_error else "result"

    # Show a short preview in the header
    first_line = content.split("\n", 1)[0]
    if len(first_line) > 80:
        first_line = first_line[:77] + "…"

    header = ft.Row(
        [
            ft.Icon(icon, color=header_color, size=13),
            ft.Text(
                label,
                color=header_color,
                size=11,
                weight=ft.FontWeight.W_600,
            ),
            ft.Text(
                first_line,
                color=theme.TEXT_TERTIARY,
                size=11,
                font_family=theme.FONT_MONO,
                no_wrap=True,
                overflow=ft.TextOverflow.ELLIPSIS,
                expand=True,
            ),
        ],
        spacing=6,
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    body_text = ft.Text(
        content,
        font_family=theme.FONT_MONO,
        size=11,
        color=theme.ERROR if is_error else theme.TEXT_SECONDARY,
        selectable=True,
    )

    return _make_collapsible_panel(
        header, body_text,
        bg=theme.TOOL_RESULT_BG,
        border_color=theme.TOOL_RESULT_BORDER,
        margin_top=2, margin_bottom=10,
        initially_open=False,
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
                        color=theme.ACCENT,
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

    return ft.Container(
        content=ft.Column(
            [
                ft.Text(
                    "O p e n H",
                    color=theme.ACCENT,
                    size=32,
                    weight=ft.FontWeight.W_300,
                    text_align=ft.TextAlign.CENTER,
                    font_family=theme.FONT_SANS,
                ),
                ft.Text(
                    "What can I help you with?",
                    color=theme.TEXT_TERTIARY,
                    size=14,
                    text_align=ft.TextAlign.CENTER,
                ),
                cwd_row,
            ],
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
    from ..settings import ANTHROPIC_MODELS, GEMINI_MODELS

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
    attachments: list[tuple[int, str]] | None = None,
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

    send_btn = ft.IconButton(
        icon=ft.Icons.ARROW_UPWARD,
        icon_color=theme.TEXT_ON_ACCENT,
        bgcolor=theme.ACCENT if not busy else theme.BG_ELEVATED,
        icon_size=18,
        tooltip="Send (Enter)",
        on_click=lambda e: on_send(),
        style=ft.ButtonStyle(
            shape=ft.CircleBorder(),
            padding=ft.padding.all(10),
        ),
        disabled=busy,
    )

    bottom_row = ft.Row(
        [
            attach_btn,
            ft.Container(width=4),
            perms_btn,
            ft.Container(expand=True),
            model_btn,
            ft.Container(width=6),
            send_btn,
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    # Attachment chips row (above text input)
    box_children: list[ft.Control] = []
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

    box_children.extend([input_field, ft.Container(height=4), bottom_row])

    box = ft.Container(
        content=ft.Column(
            box_children,
            spacing=0,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ),
        bgcolor=theme.BG_DEEPEST,
        border=ft.border.all(1, theme.BORDER_SUBTLE),
        border_radius=theme.RADIUS_LG,
        padding=ft.padding.only(left=14, right=14, top=12, bottom=8),
    )

    return ft.Container(
        content=box,
        padding=ft.padding.only(
            left=theme.PADDING_GUTTER,
            right=theme.PADDING_GUTTER,
            top=6,
            bottom=14,
        ),
    )
