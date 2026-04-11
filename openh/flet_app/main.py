"""Flet desktop chat app — Claude.app-style GUI on top of openh's backend.

Layout:
  ┌──────────┬──────────────────────────────────────┐
  │ sidebar  │  top bar (model pill + tokens)      │
  │          ├──────────────────────────────────────┤
  │ new chat │                                      │
  │ recents  │    scrollable messages column        │
  │          │    (centered, max 760px wide)        │
  │ profile  │                                      │
  │          │    ┌────────────────────────────┐   │
  │          │    │   rounded input box        │   │
  │          │    │   [+]                [↑]   │   │
  │          │    └────────────────────────────┘   │
  └──────────┴──────────────────────────────────────┘
"""
from __future__ import annotations

from typing import Any

import flet as ft

from ..agent import Agent
from ..commands import CommandContext, CommandDispatcher
from ..config import SYSTEM_PROMPT, load_config, load_system_prompt
from .. import prompts as prompts_mod
from ..settings import Settings, load_settings, save_settings
from .settings_dialog import SettingsDialog
from ..messages import (
    MessageStop,
    StreamEvent,
    TextDelta,
    ToolResultEvent,
    ToolUseEnd,
    ToolUseStart,
    Usage,
)
from ..cc_compat import (
    CCSessionMeta,
    JsonlSessionWriter,
    ensure_project_dirs,
    group_sessions,
    list_all_recent_sessions,
    list_sessions_for_cwd,
    new_session_uuid,
    apply_flags,
    read_session_jsonl,
    save_session_meta,
    session_jsonl_path,
    set_session_flag,
)
# Keep old persistence module for backward compat (no longer used)
SessionMeta = CCSessionMeta
from ..providers import get_provider
from ..pricing import estimate_cost_usd
from ..session import AgentSession
from ..tools import default_tools
from . import theme, widgets
from .permission_dialog import PermissionDialog


class OpenHApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.config = load_config()
        self.settings: Settings = load_settings()

        # Apply persisted model choice onto the config (before constructing provider)
        if self.settings.anthropic_model:
            self.config = type(self.config)(
                anthropic_api_key=self.config.anthropic_api_key,
                gemini_api_key=self.config.gemini_api_key,
                anthropic_model=self.settings.anthropic_model,
                gemini_model=self.settings.gemini_model,
                cwd=self.config.cwd,
            )

        if not self.config.anthropic_api_key and not self.config.gemini_api_key:
            page.add(
                widgets.error_panel(
                    "No API keys found in /Users/hyeon/Projects/.env. "
                    "Set ANTHROPIC_API_KEY and/or GEMINI_API_KEY."
                )
            )
            return

        # Prefer the persisted provider if its key is available
        initial = self.settings.active_provider
        if initial == "anthropic" and not self.config.anthropic_api_key:
            initial = "gemini"
        elif initial == "gemini" and not self.config.gemini_api_key:
            initial = "anthropic"
        try:
            provider = get_provider(initial, self.config)
        except Exception as exc:  # noqa: BLE001
            page.add(widgets.error_panel(f"Failed to start provider {initial}: {exc}"))
            return

        import time
        sid = new_session_uuid()
        self.session = AgentSession(
            config=self.config,
            provider=provider,
            tools=default_tools(),
            session_id=sid,
            title="",
            created_at=time.time(),
        )
        ensure_project_dirs(self.config.cwd)
        self._jsonl_writer = JsonlSessionWriter(self.config.cwd, sid)
        # Load MCP tools asynchronously
        self._mcp_loaded = False
        self.permission_dialog = PermissionDialog(page)
        self._busy = False
        self._current_task: "asyncio.Task | None" = None
        self._skip_permissions = self.settings.skip_permissions
        self._file_picker = ft.FilePicker()
        self._dispatcher = CommandDispatcher()
        self._window_initialized = False

        # Apply persisted theme + color/font presets
        import openh.flet_app.theme as theme_mod
        theme_mod.set_color_preset(self.settings.color_preset)
        theme_mod.set_font(self.settings.font_preset)
        theme_mod.set_mode(self.settings.theme_mode if self.settings.theme_mode in ("dark", "light") else "dark")

        # Sidebar state
        self._sidebar_visible = True
        self._sidebar_width: float = float(self.settings.sidebar_width or theme.SIDEBAR_WIDTH)
        self._sidebar_width_min = 200.0
        self._sidebar_width_max = 500.0

        # All recent sessions across every project dir (flat, newest first)
        self._session_metas: list[CCSessionMeta] = apply_flags(list_all_recent_sessions())
        self._current_title = ""

        # Streaming state
        self._stream_text_buf: list[str] = []
        self._stream_message_widget: ft.Container | None = None
        self._thinking_widget: ft.Container | None = None
        self._welcome_widget: ft.Container | None = None
        self._message_end_spacer = ft.Container(height=20)
        self._session_cache: dict[str, tuple[int, int, list[Any], dict[str, Any]]] = {}
        self._queued_turns: list[tuple[str, list[Any]]] = []
        self._live_tool_entries: list[tuple[str, dict[str, Any], str | None, bool]] = []
        self._live_tool_stack_widget: ft.Control | None = None
        self._content_width = theme.MESSAGE_MAX_WIDTH
        self._stick_to_bottom = True
        self._scroll_in_flight = False
        self._scroll_requested = False
        self._pending_scroll_animated = False
        self._jsonl_written_count = 0
        self._busy_note_active = False
        self._busy_indicator_host: ft.Container | None = None
        self._busy_indicator_letters: list[ft.Text] = []
        self._busy_indicator_task_running = False
        self._busy_indicator_token = 0

        self._build_ui()
        if not self._restore_last_session():
            self._remember_current_session()

    # ---------------- UI scaffolding ----------------

    def _build_ui(self) -> None:
        self.page.title = "openh"
        self.page.bgcolor = theme.BG_PAGE
        self.page.padding = 0
        self.page.theme_mode = ft.ThemeMode.DARK if theme.is_dark() else ft.ThemeMode.LIGHT
        _ts = ft.TextStyle(color=theme.TEXT_PRIMARY)
        self.page.theme = ft.Theme(
            color_scheme_seed=theme.ACCENT,
            color_scheme=ft.ColorScheme(
                on_surface=theme.TEXT_PRIMARY,
                on_surface_variant=theme.TEXT_SECONDARY,
                surface=theme.BG_PAGE,
                surface_container=theme.BG_ELEVATED,
                surface_container_high=theme.BG_ELEVATED,
                surface_container_highest=theme.BG_ELEVATED,
                surface_container_low=theme.BG_PAGE,
                surface_tint="#00000000",  # no tint overlay
            ),
            font_family=theme.FONT_SANS,
            text_theme=ft.TextTheme(
                body_large=_ts, body_medium=_ts, body_small=_ts,
                title_large=_ts, title_medium=_ts, title_small=_ts,
                label_large=_ts, label_medium=_ts, label_small=_ts,
                headline_large=_ts, headline_medium=_ts, headline_small=_ts,
                display_large=_ts, display_medium=_ts, display_small=_ts,
            ),
        )
        # Set window size ONLY on the very first build. Rebuilds (e.g. theme
        # toggle) must not touch user-controlled window geometry.
        if not self._window_initialized:
            self.page.window.width = self.settings.window_width
            self.page.window.height = self.settings.window_height
            self.page.window.min_width = 420
            self.page.window.min_height = 540
            self.page.window.on_event = self._on_window_event
            self._window_initialized = True

        # --- sidebar ---
        self.sidebar_holder = ft.Container()
        self._refresh_sidebar()

        # --- top bar ---
        self.top_bar_holder = ft.Container()
        self._refresh_top_bar()

        # --- message column ---
        self.message_column = ft.Column(
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            scroll_interval=80,
            on_scroll=self._on_message_scroll,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            expand=True,
        )
        self._ensure_message_end_spacer()
        self._show_welcome()

        self._content_width = self._compute_content_width()
        self._message_width_holder = ft.Container(
            content=self.message_column,
            width=self._content_width,
        )
        # Centered message container (max 760px wide)
        message_area = ft.Container(
            content=self._message_width_holder,
            alignment=ft.Alignment(0, -1),
            padding=ft.padding.symmetric(horizontal=theme.PADDING_GUTTER),
            expand=True,
        )

        # --- input ---
        self.input_field = ft.TextField(
            hint_text="Reply to openh…",
            hint_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=15),
            text_style=ft.TextStyle(
                color=theme.TEXT_PRIMARY,
                size=15,
                font_family=theme.FONT_SANS,
            ),
            border=ft.InputBorder.NONE,
            filled=False,
            multiline=True,
            min_lines=1,
            max_lines=10,
            shift_enter=True,
            on_submit=self._on_submit,
            autofocus=True,
            expand=True,
            content_padding=ft.padding.only(top=4, bottom=4),
            cursor_color=theme.ACCENT,
        )
        self.input_holder = ft.Container()
        self._refresh_input()

        # --- bottom status bar ---
        self.status_bar_holder = ft.Container()
        self._refresh_status_bar()

        # --- assemble main column (top bar + messages + input) ---
        # Use a Column: messages expand, input stays at natural height at bottom.
        # Messages have bottom padding so content scrolls behind input area.
        main_col = ft.Container(
            content=ft.Column(
                [
                    self.top_bar_holder,
                    message_area,
                    self.input_holder,
                ],
                spacing=0,
                expand=True,
            ),
            expand=True,
            bgcolor=theme.BG_PAGE,
        )

        # --- resize handle for the sidebar ---
        # Thin vertical bar wrapped in a GestureDetector listening for
        # horizontal drags. Fixed width so the hit area is always 6px wide.
        # We keep a reference so it can be hidden when the sidebar collapses.
        self._resize_handle = ft.GestureDetector(
            content=ft.Container(
                width=2,
                bgcolor=theme.BORDER_FAINT,
            ),
            drag_interval=10,
            on_horizontal_drag_update=self._on_sidebar_drag,
            on_horizontal_drag_end=self._flush_sidebar_width,
            mouse_cursor=ft.MouseCursor.RESIZE_LEFT_RIGHT,
            visible=self._sidebar_visible,
        )
        resize_handle = self._resize_handle

        # --- file picker (Service, must be registered before first use) ---
        self.page.services.append(self._file_picker)

        # --- full layout: (sidebar | handle | main) + bottom status bar ---
        self.page.add(
            ft.Column(
                [
                    ft.Row(
                        [
                            self.sidebar_holder,
                            resize_handle,
                            main_col,
                        ],
                        spacing=0,
                        expand=True,
                        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
                    ),
                    self.status_bar_holder,
                ],
                spacing=0,
                expand=True,
            )
        )

        self.page.on_keyboard_event = self._on_key

        # Load MCP tools in the background
        if not self._mcp_loaded:
            self.page.run_task(self._load_mcp_tools_async)

    async def _load_mcp_tools_async(self) -> None:
        if self._mcp_loaded:
            return
        self._mcp_loaded = True
        try:
            from ..mcp import build_mcp_tools
            tools = await build_mcp_tools()
            if tools:
                self.session.tools.extend(tools)
                self._append_to_messages(
                    widgets.system_note(f"loaded {len(tools)} MCP tool(s)")
                )
        except Exception:
            pass

    # ---------------- refreshers ----------------

    def _refresh_sidebar(self) -> None:
        if self._sidebar_visible:
            import os
            from pathlib import Path
            groups_by_name: dict[str, list[tuple[str, str, str, bool, bool]]] = {}
            grouped = group_sessions(self._session_metas)

            def project_display(cwd: str) -> str:
                if not cwd:
                    return ""
                p = Path(cwd)
                parts = p.parts
                if len(parts) >= 2:
                    return ".../" + "/".join(parts[-2:])
                return str(p)

            # Collect pinned sessions into a separate group at the top
            pinned = [m for m in self._session_metas if m.starred]
            if pinned:
                pinned.sort(key=lambda m: -m.mtime)
                groups_by_name["Pinned"] = [
                    (m.session_id, m.title or "Untitled", project_display(m.cwd), m.starred, m.hidden)
                    for m in pinned
                ]
            pinned_ids = {m.session_id for m in pinned}

            for gname, items in grouped.items():
                sorted_items = sorted(items, key=lambda m: -m.mtime)
                entries = [
                    (m.session_id, m.title or "Untitled", project_display(m.cwd), m.starred, m.hidden)
                    for m in sorted_items if m.session_id not in pinned_ids
                ]
                if entries:
                    groups_by_name[gname] = entries
            bar = widgets.sidebar(
                groups=groups_by_name,
                active_session_id=self.session.session_id,
                on_new_chat=self._new_chat,
                on_select=self._select_session,
                on_delete=self._delete_session_by_id,
                on_star=self._toggle_star,
                on_hide=self._toggle_hide,
                show_hidden=getattr(self, "_show_hidden", False),
                width=int(self._sidebar_width),
            )
        else:
            bar = ft.Container(width=0)
        self.sidebar_holder.content = bar
        try:
            self.sidebar_holder.update()
        except Exception:
            pass

    def _on_sidebar_drag(self, e) -> None:
        if not self._sidebar_visible:
            return
        # Flet 0.84: DragUpdateEvent exposes `primary_delta` (main axis)
        # and `local_delta` / `global_delta` (Offset with x, y).
        delta = float(getattr(e, "primary_delta", 0.0) or 0.0)
        if delta == 0.0:
            ld = getattr(e, "local_delta", None)
            if ld is not None:
                delta = float(getattr(ld, "x", 0.0) or 0.0)
        if delta == 0.0:
            return
        new_w = self._sidebar_width + delta
        if new_w < self._sidebar_width_min:
            new_w = self._sidebar_width_min
        elif new_w > self._sidebar_width_max:
            new_w = self._sidebar_width_max
        if abs(new_w - self._sidebar_width) < 0.5:
            return
        self._sidebar_width = new_w
        self.sidebar_holder.width = new_w
        # Also resize the widget inside the holder if it has its own width
        inner = self.sidebar_holder.content
        if inner is not None and hasattr(inner, "width"):
            try:
                inner.width = new_w
            except Exception:
                pass
        try:
            self.sidebar_holder.update()
        except Exception:
            pass
        # Mark dirty; actual save happens on drag-end (see below).
        self.settings.sidebar_width = int(new_w)
        self._sidebar_width_dirty = True
        self._update_content_width()

    def _flush_sidebar_width(self, e=None) -> None:
        if getattr(self, "_sidebar_width_dirty", False):
            self._sidebar_width_dirty = False
            try:
                save_settings(self.settings)
            except Exception:
                pass

    def _on_window_event(self, e) -> None:
        try:
            event_type = getattr(e, "data", "") or getattr(e, "type", "") or str(e)
            w = int(self.page.window.width or 0)
            h = int(self.page.window.height or 0)
            if w > 100 and h > 100:
                changed = (w != self.settings.window_width or h != self.settings.window_height)
                if changed:
                    self.settings.window_width = w
                    self.settings.window_height = h
                    save_settings(self.settings)
                    self._update_content_width()
        except Exception:
            pass

    def _get_system_prompt(self) -> str:
        """Return the effective system prompt.

        Priority: session override > session preset > global preset > built-in.
        """
        # 1. Per-session custom override
        if self.session.prompt_override:
            return self.session.prompt_override
        # 2. Per-session preset
        session_preset = (self.session.prompt_preset or "").strip()
        if session_preset and session_preset.lower() != prompts_mod.BUILTIN_NAME:
            preset = prompts_mod.get_preset(session_preset)
            if preset is not None and preset.text.strip():
                return preset.text
        # 3. Global active preset
        active = (self.settings.active_prompt or "").strip()
        if active and active.lower() != prompts_mod.BUILTIN_NAME:
            preset = prompts_mod.get_preset(active)
            if preset is not None and preset.text.strip():
                return preset.text
        return load_system_prompt()

    def _refresh_top_bar(self, note: str = "") -> None:
        # Determine prompt label for the pill
        p_label = self.session.prompt_preset or self.settings.active_prompt or "default"
        if self.session.prompt_override:
            p_label = f"{p_label} (edited)"
        self._busy_note_active = bool(note)
        busy_indicator = self._ensure_busy_indicator() if note else None
        if note:
            self._start_busy_indicator_animation()
        else:
            self._stop_busy_indicator_animation()
        bar = widgets.top_bar(
            title=self._current_title or "New chat",
            on_toggle_sidebar=self._toggle_sidebar,
            on_rename=self._open_rename_dialog,
            on_toggle_theme=self._toggle_theme,
            on_open_settings=self._open_settings,
            on_edit_prompt=self._open_prompt_editor,
            prompt_label=p_label,
            busy_indicator=busy_indicator,
        )
        self.top_bar_holder.content = bar
        try:
            self.top_bar_holder.update()
        except Exception:
            pass

    def _ensure_busy_indicator(self) -> ft.Container:
        if self._busy_indicator_host is not None:
            return self._busy_indicator_host
        letters: list[ft.Text] = []
        for ch in "thinking...":
            letters.append(
                ft.Text(
                    ch,
                    color=theme.ACCENT,
                    size=12,
                    italic=True,
                    opacity=0.6,
                    offset=ft.Offset(0, 0),
                    animate_offset=180,
                    animate_opacity=180,
                )
            )
        self._busy_indicator_letters = letters
        self._busy_indicator_host = ft.Container(
            content=ft.Row(
                letters,
                spacing=0,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.only(left=2, right=2),
        )
        return self._busy_indicator_host

    def _start_busy_indicator_animation(self) -> None:
        if self._busy_indicator_task_running:
            return
        try:
            self.page.run_task(self._animate_busy_indicator)
        except Exception:
            pass

    def _stop_busy_indicator_animation(self) -> None:
        self._busy_indicator_token += 1
        for letter in self._busy_indicator_letters:
            letter.offset = ft.Offset(0, 0)
            letter.opacity = 0.6
        try:
            if self._busy_indicator_host is not None:
                self._busy_indicator_host.update()
        except Exception:
            pass

    async def _animate_busy_indicator(self) -> None:
        import asyncio

        self._busy_indicator_task_running = True
        self._busy_indicator_token += 1
        token = self._busy_indicator_token
        try:
            while token == self._busy_indicator_token and self._busy_note_active:
                letters = self._busy_indicator_letters
                for idx, letter in enumerate(letters):
                    if token != self._busy_indicator_token or not self._busy_note_active:
                        break
                    for j, other in enumerate(letters):
                        other.offset = ft.Offset(0, -0.18 if j == idx else 0)
                        other.opacity = 1.0 if j == idx else 0.42
                    if self._busy_indicator_host is not None:
                        self._busy_indicator_host.update()
                    await asyncio.sleep(0.07)
                for letter in letters:
                    letter.offset = ft.Offset(0, 0)
                    letter.opacity = 0.6
                if self._busy_indicator_host is not None:
                    self._busy_indicator_host.update()
                await asyncio.sleep(0.16)
        except Exception:
            pass
        finally:
            self._busy_indicator_task_running = False

    def _refresh_status_bar(self) -> None:
        model = getattr(self.session.provider, "model", "")
        # Last turn's input_tokens approximates current context size
        context_tokens = self.session.last_input_tokens if hasattr(self.session, "last_input_tokens") else 0
        # Context limit per model
        ctx_limits = {
            "claude-opus-4-6": 1_000_000, "claude-opus-4": 200_000,
            "claude-sonnet-4-6": 1_000_000, "claude-sonnet-4-5": 200_000,
            "claude-sonnet-4": 200_000, "claude-haiku-4-5": 200_000,
            "claude-haiku-4": 200_000,
            "gemini-3.1-pro-preview": 1_000_000, "gemini-2.5-pro": 1_000_000,
            "gemini-2.5-flash": 1_000_000, "gemini-2.0-flash": 1_000_000,
            "gemini-2.0-flash-exp": 1_000_000,
        }
        context_limit = ctx_limits.get(model, 200_000)
        bar = widgets.bottom_status_bar(
            cwd=self.session.cwd,
            in_tokens=self.session.total_input_tokens,
            out_tokens=self.session.total_output_tokens,
            model=model,
            cost_usd=self.session.total_estimated_cost_usd,
            context_tokens=context_tokens,
            context_limit=context_limit,
        )
        self.status_bar_holder.content = bar
        try:
            self.status_bar_holder.update()
        except Exception:
            pass

    def _refresh_input(self) -> None:
        pending = getattr(self, "_pending_media", None) or []
        box = widgets.input_area(
            input_field=self.input_field,
            on_send=lambda: self._on_submit(None),
            on_attach=self._on_attach,
            on_toggle_permissions=self._toggle_permissions,
            on_pick_model=self._pick_model,
            provider_name=self.session.provider.name,
            model=self.session.provider.model,
            skip_permissions=self._skip_permissions,
            busy=self._busy,
            on_stop=self._stop_generation,
            content_width=self._content_width,
            attachments=[(i, type(b).__name__, getattr(b, "data_base64", "")) for i, b in enumerate(pending)],
            queued_inputs=[
                text + (" [media]" if media_blocks else "")
                for text, media_blocks in self._queued_turns
            ],
            on_remove_queued_input=self._remove_queued_turn,
            on_remove_attachment=self._remove_attachment,
        )
        self.input_holder.content = box
        try:
            self.input_holder.update()
        except Exception:
            pass

    def _compute_content_width(self) -> int:
        window_w = int(
            getattr(self.page, "width", 0)
            or self.page.window.width
            or self.settings.window_width
            or 0
        )
        sidebar_w = int(self._sidebar_width) if self._sidebar_visible else 0
        handle_w = 2 if self._sidebar_visible else 0
        gutter = 14 if window_w < 720 else theme.PADDING_GUTTER
        main_area_w = max(window_w - sidebar_w - handle_w, 260)
        inner_w = max(220, main_area_w - (gutter * 2))
        return int(min(theme.MESSAGE_MAX_WIDTH, inner_w))

    def _update_content_width(self) -> None:
        new_width = self._compute_content_width()
        if new_width == getattr(self, "_content_width", 0):
            return
        self._content_width = new_width
        holder = getattr(self, "_message_width_holder", None)
        if holder is not None:
            holder.width = new_width
            try:
                holder.update()
            except Exception:
                pass
        if hasattr(self, "input_holder"):
            self._refresh_input()

    def _on_message_scroll(self, e) -> None:
        try:
            threshold = max(72.0, float(getattr(e, "viewport_dimension", 0.0) or 0.0) * 0.15)
            extent_after = float(getattr(e, "extent_after", 0.0) or 0.0)
            self._stick_to_bottom = extent_after <= threshold
        except Exception:
            pass

    def _remember_current_session(self, *, save: bool = True) -> None:
        self.settings.last_session_id = self.session.session_id
        self.settings.last_session_cwd = self.session.cwd
        if not save:
            return
        try:
            save_settings(self.settings)
        except Exception:
            pass

    def _restore_last_session(self) -> bool:
        last_session_id = (getattr(self.settings, "last_session_id", "") or "").strip()
        if not last_session_id:
            return False
        if not any(meta.session_id == last_session_id for meta in self._session_metas):
            return False
        self._select_session(last_session_id)
        return True

    def _pick_model(self, provider_name: str, model: str) -> None:
        """Called when the user picks a specific provider+model from the dropdown."""
        if self._busy:
            return
        # Update settings
        self.settings.active_provider = provider_name
        if provider_name == "anthropic":
            self.settings.anthropic_model = model
        else:
            self.settings.gemini_model = model

        # Rebuild config + provider
        new_config = type(self.config)(
            anthropic_api_key=self.config.anthropic_api_key,
            gemini_api_key=self.config.gemini_api_key,
            anthropic_model=self.settings.anthropic_model,
            gemini_model=self.settings.gemini_model,
            cwd=self.config.cwd,
        )
        self.config = new_config
        self.session.config = new_config
        try:
            new_provider = get_provider(provider_name, self.config)
        except Exception as exc:  # noqa: BLE001
            self._append_to_messages(
                widgets.error_panel(f"can't switch: {exc}")
            )
            return
        self.session.switch_provider(new_provider)
        save_settings(self.settings)
        self._refresh_top_bar()
        self._refresh_input()
        self._append_to_messages(
            widgets.system_note(f"switched to {provider_name}:{model}")
        )
        self._scroll_to_end(force=True)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            page=self.page,
            current=self.settings,
            on_save=self._apply_settings,
            session=self.session,
        )
        dialog.open()

    def _apply_settings(self, new_settings: Settings) -> None:
        """Called when the user clicks Save in the SettingsDialog."""
        old_provider = self.settings.active_provider
        old_anth = self.settings.anthropic_model
        old_gem = self.settings.gemini_model

        self.settings = new_settings
        self._skip_permissions = new_settings.skip_permissions

        # Update Config + reload provider if model changed
        new_config = type(self.config)(
            anthropic_api_key=self.config.anthropic_api_key,
            gemini_api_key=self.config.gemini_api_key,
            anthropic_model=new_settings.anthropic_model,
            gemini_model=new_settings.gemini_model,
            cwd=self.config.cwd,
        )
        self.config = new_config
        self.session.config = new_config

        provider_needs_reload = (
            new_settings.active_provider != old_provider
            or (new_settings.active_provider == "anthropic" and new_settings.anthropic_model != old_anth)
            or (new_settings.active_provider == "gemini" and new_settings.gemini_model != old_gem)
        )
        if provider_needs_reload:
            try:
                new_provider = get_provider(new_settings.active_provider, self.config)
                self.session.switch_provider(new_provider)
            except Exception as exc:  # noqa: BLE001
                self._append_to_messages(
                    widgets.error_panel(f"provider reload failed: {exc}")
                )
        # Propagate the new auto-compact threshold globally
        import openh.config as cfg_mod
        cfg_mod.AUTO_COMPACT_THRESHOLD = int(new_settings.auto_compact_threshold)
        cfg_mod.MAX_OUTPUT_TOKENS = int(new_settings.max_output_tokens)

        # Apply appearance presets and full rebuild
        theme.set_color_preset(new_settings.color_preset)
        theme.set_font(new_settings.font_preset)
        theme.set_mode(theme.current_mode())

        save_settings(self.settings)

        # Full UI rebuild to apply new colors everywhere
        self._rebuild_ui_after_theme_change()
    def _toggle_sidebar(self) -> None:
        self._sidebar_visible = not self._sidebar_visible
        if hasattr(self, "_resize_handle") and self._resize_handle is not None:
            self._resize_handle.visible = self._sidebar_visible
            try:
                self._resize_handle.update()
            except Exception:
                pass
        self._refresh_sidebar()
        self._update_content_width()
        # Restore scroll position after layout change
        self._scroll_to_end()

    def _stop_generation(self) -> None:
        """Cancel the current model turn."""
        if self._current_task is not None:
            self._current_task.cancel()
            self._current_task = None
        self._finalize_streaming_message()
        # Add interruption marker
        from ..messages import TextBlock
        self._append_to_messages(
            widgets.system_note("[Request interrupted by user]")
        )
        self._busy = False
        self._refresh_input()
        self._refresh_top_bar()
        self._refresh_status_bar()
        self._autosave()

    def _toggle_permissions(self) -> None:
        self._skip_permissions = not self._skip_permissions
        self._refresh_input()

    def _toggle_theme(self) -> None:
        theme.set_mode("light" if theme.is_dark() else "dark")
        self.settings.theme_mode = "dark" if theme.is_dark() else "light"
        save_settings(self.settings)
        self.page.theme_mode = ft.ThemeMode.DARK if theme.is_dark() else ft.ThemeMode.LIGHT
        self.page.bgcolor = theme.BG_PAGE
        # Re-render everything that reads theme tokens
        self._rebuild_ui_after_theme_change()

    def _rebuild_ui_after_theme_change(self) -> None:
        """Full page rebuild after toggling the theme."""
        self.page.controls.clear()
        self._welcome_widget = None
        self._stream_message_widget = None
        self._build_ui()
        if self.session.messages:
            self._hide_welcome()
            self._replay_messages_all()
        self._scroll_to_end()
        try:
            self.page.update()
        except Exception:
            pass

    def _replay_messages_all(self) -> None:
        """Replay all session messages, pairing tool_call + tool_result into combined panels."""
        from ..messages import TextBlock, ToolResultBlock, ToolUseBlock

        # Build a map of tool_use_id → ToolResultBlock for matching
        result_map: dict[str, ToolResultBlock] = {}
        replayed_widgets: list[ft.Control] = []

        def queue(widget: ft.Control) -> None:
            replayed_widgets.append(widget)

        for msg in self.session.messages:
            if msg.role == "user":
                for b in msg.content:
                    if isinstance(b, ToolResultBlock):
                        result_map[b.tool_use_id] = b

        for msg_index, msg in enumerate(self.session.messages):
            if msg.role == "user":
                text_parts = []
                for b in msg.content:
                    if isinstance(b, TextBlock):
                        t = b.text.strip()
                        if t.startswith("<environment>"):
                            continue
                        if t.startswith("[Conversation compacted") or t.startswith("[Prior conversation summary"):
                            continue
                        text_parts.append(b.text)
                    # ToolResultBlocks are rendered with their matching tool_call above
                if text_parts:
                    queue(
                        widgets.user_bubble(
                            "\n".join(text_parts),
                            on_edit=self._on_edit_message,
                            msg_index=msg_index,
                            content_width=self._content_width,
                        )
                    )
            else:
                text_parts = []
                tool_entries: list[tuple[str, dict[str, Any], str | None, bool]] = []

                def flush_tool_entries() -> None:
                    nonlocal tool_entries
                    if not tool_entries:
                        return
                    queue(self._build_tool_panel(tool_entries))
                    tool_entries = []

                for b in msg.content:
                    if isinstance(b, TextBlock):
                        if tool_entries:
                            flush_tool_entries()
                        t = b.text.strip()
                        if t in ("Acknowledged. Ready to help.", "Understood. Continuing from the recent context."):
                            continue
                        text_parts.append(b.text)
                    elif isinstance(b, ToolUseBlock):
                        if text_parts:
                            queue(widgets.assistant_message("".join(text_parts)))
                            text_parts = []
                        # Find matching result
                        result = result_map.get(b.id)
                        tool_entries.append(
                            (
                                b.name,
                                b.input,
                                result.content if result else None,
                                result.is_error if result else False,
                            )
                        )
                flush_tool_entries()
                if text_parts:
                    queue(
                        widgets.assistant_message(
                            "".join(text_parts),
                            on_retry=self._on_retry_message,
                            msg_index=msg_index,
                        )
                    )

        self._extend_messages(replayed_widgets)

    # ---- Edit / Retry ----

    def _on_edit_message(self, msg_index: int, original_text: str) -> None:
        """User clicked edit on a user bubble — show confirm modal with editable text."""
        if self._busy:
            return
        field = ft.TextField(
            value=original_text,
            multiline=True,
            min_lines=2,
            max_lines=10,
            border_color=theme.BORDER_SUBTLE,
            cursor_color=theme.ACCENT,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=14),
        )
        n_after = len(self.session.messages) - msg_index - 1
        warning = f"{n_after} message(s) after this will be removed." if n_after > 0 else ""

        def do_edit(e):
            self.page.pop_dialog()
            new_text = (field.value or "").strip()
            if not new_text:
                return
            # Truncate history from this point
            self.session.messages = self.session.messages[:msg_index]
            self.session.reset_model_messages()
            self._jsonl_written_count = min(
                getattr(self, "_jsonl_written_count", 0), msg_index
            )
            self._persist_session_snapshot(rewrite=True)
            # Re-render
            self.message_column.controls.clear()
            self._welcome_widget = None
            self._stream_message_widget = None
            self._replay_messages_all()
            # Submit as new turn
            self.input_field.value = new_text
            self.input_field.update()
            self._on_submit(None)

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=theme.BG_ELEVATED,
            title=ft.Text("Edit message", color=theme.TEXT_PRIMARY, size=16),
            content=ft.Column(
                [
                    ft.Container(content=field, width=480),
                    ft.Text(warning, color=theme.WARN, size=12) if warning else ft.Container(),
                ],
                tight=True,
                spacing=8,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog()),
                ft.ElevatedButton(
                    "Resend",
                    on_click=do_edit,
                    style=ft.ButtonStyle(bgcolor=theme.ACCENT, color=theme.TEXT_ON_ACCENT),
                ),
            ],
        )
        self.page.show_dialog(dialog)

    def _on_retry_message(self, msg_index: int) -> None:
        """User clicked retry on an assistant message — confirm and regenerate."""
        if self._busy:
            return
        n_after = len(self.session.messages) - msg_index
        warning = f"This will remove {n_after} message(s) and regenerate the response."

        def do_retry(e):
            self.page.pop_dialog()
            # Keep everything before this assistant message
            self.session.messages = self.session.messages[:msg_index]
            self.session.reset_model_messages()
            self._jsonl_written_count = min(
                getattr(self, "_jsonl_written_count", 0), msg_index
            )
            self._persist_session_snapshot(rewrite=True)
            # Re-render
            self.message_column.controls.clear()
            self._welcome_widget = None
            self._stream_message_widget = None
            self._replay_messages_all()
            # Re-run the agent from current state
            self.page.run_task(self._retry_turn_async)

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=theme.BG_ELEVATED,
            title=ft.Text("Retry", color=theme.TEXT_PRIMARY, size=16),
            content=ft.Text(warning, color=theme.TEXT_SECONDARY, size=14),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog()),
                ft.ElevatedButton(
                    "Retry",
                    on_click=do_retry,
                    style=ft.ButtonStyle(bgcolor=theme.ACCENT, color=theme.TEXT_ON_ACCENT),
                ),
            ],
        )
        self.page.show_dialog(dialog)

    async def _retry_turn_async(self) -> None:
        """Re-run the model from current message state (no new user message)."""
        self._busy = True
        self._refresh_input()
        try:
            from ..agent import Agent
            from ..compaction import compact_messages, should_compact
            agent = Agent(
                session=self.session,
                system_prompt=self._get_system_prompt(),
                event_sink=self._handle_stream_event,
                permission_cb=self._ask_permission,
            )
            if should_compact(self.session.model_messages):
                self.session.model_messages = await compact_messages(
                    self.session.model_messages, self.session.provider
                )
            await agent._drive_loop()
        except Exception as exc:
            self._append_to_messages(
                widgets.error_panel(str(exc))
            )
        finally:
            self._busy = False
            self._finalize_streaming_message()
            self._refresh_input()
            self._refresh_top_bar()
            self._refresh_status_bar()
            self._autosave()
            self._focus_input()
            self._scroll_to_end()

    def _open_prompt_editor(self) -> None:
        """Open a dialog to edit this session's system prompt."""
        current_text = self._get_system_prompt()
        presets = prompts_mod.list_presets()
        preset_names = [p.name for p in presets]

        field = ft.TextField(
            value=current_text,
            multiline=True,
            min_lines=8,
            max_lines=20,
            border_color=theme.BORDER_SUBTLE,
            cursor_color=theme.ACCENT,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=12, font_family=theme.FONT_MONO),
        )

        def load_preset(name):
            p = prompts_mod.get_preset(name)
            if p:
                field.value = p.text
                field.update()

        preset_items = [
            ft.PopupMenuItem(
                content=name,
                on_click=lambda e, n=name: load_preset(n),
            )
            for name in preset_names
        ]
        preset_btn = ft.PopupMenuButton(
            items=preset_items,
            content=ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.BOOKMARK_OUTLINE, color=theme.TEXT_SECONDARY, size=14),
                        ft.Text("Load preset", color=theme.TEXT_SECONDARY, size=12),
                    ],
                    spacing=4, tight=True,
                ),
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
            ),
        )

        def apply(e):
            new_text = (field.value or "").strip()
            if new_text == prompts_mod.resolve_active(self.settings.active_prompt):
                # Same as global — clear override
                self.session.prompt_override = ""
                self.session.prompt_preset = ""
            else:
                self.session.prompt_override = new_text
            self.page.pop_dialog()
            self._refresh_top_bar()

        def reset(e):
            self.session.prompt_override = ""
            self.session.prompt_preset = ""
            self.page.pop_dialog()
            self._refresh_top_bar()

        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=theme.BG_ELEVATED,
            title=ft.Row(
                [
                    ft.Text("Session prompt", color=theme.TEXT_PRIMARY, size=16),
                    ft.Container(expand=True),
                    preset_btn,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            content=ft.Container(content=field, width=600, height=400),
            actions=[
                ft.TextButton("Reset to default", on_click=reset),
                ft.TextButton("Cancel", on_click=lambda e: self.page.pop_dialog()),
                ft.ElevatedButton(
                    "Apply to this session",
                    on_click=apply,
                    style=ft.ButtonStyle(bgcolor=theme.ACCENT, color=theme.TEXT_ON_ACCENT),
                ),
            ],
        )
        self.page.show_dialog(dialog)

    def _open_rename_dialog(self) -> None:
        field = ft.TextField(
            value=self._current_title,
            autofocus=True,
            border_color=theme.BORDER_SUBTLE,
            cursor_color=theme.ACCENT,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=14),
            on_submit=lambda e: (self._apply_rename(field.value or ""), self.page.pop_dialog()),
        )
        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=theme.BG_ELEVATED,
            title=ft.Text("Rename conversation", color=theme.TEXT_PRIMARY, size=16),
            content=ft.Container(content=field, width=480),
            actions=[
                ft.TextButton(
                    content=ft.Text("Cancel", color=theme.TEXT_SECONDARY, size=13),
                    on_click=lambda e: self.page.pop_dialog(),
                ),
                ft.FilledButton(
                    content=ft.Text("Save", color=theme.TEXT_ON_ACCENT, size=13, weight=ft.FontWeight.W_600),
                    on_click=lambda e: (self._apply_rename(field.value or ""), self.page.pop_dialog()),
                    style=ft.ButtonStyle(bgcolor=theme.ACCENT, color=theme.TEXT_ON_ACCENT),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.show_dialog(dialog)

    def _apply_rename(self, new_title: str) -> None:
        new_title = new_title.strip()
        if not new_title:
            return
        self._current_title = new_title
        self.session.title = new_title
        # Update sidebar meta
        for m in self._session_metas:
            if m.session_id == self.session.session_id:
                m.title = new_title
                break
        # Persist title to JSONL
        from ..cc_compat import save_session_title, session_jsonl_path
        try:
            p = session_jsonl_path(self.session.cwd, self.session.session_id)
            save_session_title(p, new_title)
        except Exception:
            pass
        self._refresh_top_bar()
        self._refresh_sidebar()

    def _show_welcome(self) -> None:
        if self._welcome_widget is None:
            self._welcome_widget = widgets.welcome_screen(
                cwd=self.session.cwd,
                on_change_cwd=self._change_workspace,
            )
            self._append_to_messages(self._welcome_widget)

    def _change_workspace(self) -> None:
        self.page.run_task(self._change_workspace_async)

    async def _change_workspace_async(self) -> None:
        import os
        result = await self._file_picker.get_directory_path(
            dialog_title="Select workspace",
        )
        if result:
            os.chdir(result)
            self.session.cwd = result
            self._remember_current_session()
            # Rebuild welcome to show new cwd
            self._welcome_widget = None
            self.message_column.controls.clear()
            self._show_welcome()
            self._refresh_status_bar()

    def _hide_welcome(self) -> None:
        if self._welcome_widget is not None:
            try:
                self.message_column.controls.remove(self._welcome_widget)
            except ValueError:
                pass
            self._welcome_widget = None

    # ---------------- handlers ----------------

    def _on_key(self, e: ft.KeyboardEvent) -> None:
        if e.key == "Escape" and self._busy:
            self._stop_generation()
        elif e.meta and e.key == "M":
            self._switch_model()
        elif e.meta and e.key == "L":
            self._new_chat()
        elif e.meta and e.key == "V":
            self.page.run_task(self._paste_image_async)

    async def _paste_image_async(self) -> None:
        """Handle Ctrl/Cmd+V — check for clipboard image."""
        try:
            if not hasattr(self, "_clipboard"):
                self._clipboard = ft.Clipboard()
                self.page.services.append(self._clipboard)
                self.page.update()
            img_bytes = await self._clipboard.get_image()
            if not img_bytes:
                return  # No image in clipboard, let normal paste happen
            import base64
            from ..messages import ImageBlock
            b64 = base64.b64encode(img_bytes).decode()
            if not hasattr(self, "_pending_media"):
                self._pending_media = []
            self._pending_media.append(ImageBlock(data_base64=b64, media_type="image/png"))
            self._refresh_input()
        except Exception:
            pass  # No image, normal paste proceeds

    def _build_command_ctx(self) -> CommandContext:
        def switch_to(target: str) -> None:
            try:
                new_provider = get_provider(target, self.config)
                self.session.switch_provider(new_provider)
                self._refresh_top_bar()
                self._refresh_input()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(str(exc))

        def set_title(new_title: str) -> None:
            self._current_title = new_title
            self.session.title = new_title
            self._refresh_top_bar()

        def compact_now() -> None:
            self.page.run_task(self._compact_now_async)

        def init_claude_md() -> None:
            self.page.run_task(self._init_claude_md_async)

        return CommandContext(
            session=self.session,
            on_clear=self._new_chat,
            on_switch_model=switch_to,
            on_toggle_theme=self._toggle_theme,
            on_compact_now=compact_now,
            on_init=init_claude_md,
            set_title=set_title,
        )

    async def _compact_now_async(self) -> None:
        from ..compaction import compact_messages
        if self._busy or not self.session.model_messages:
            return
        self._busy = True
        self._refresh_top_bar(note="compacting…")
        try:
            self.session.model_messages = await compact_messages(
                self.session.model_messages, self.session.provider
            )
        except Exception as exc:  # noqa: BLE001
            self._append_to_messages(
                widgets.error_panel(f"compact failed: {exc}")
            )
        finally:
            self._busy = False
            self._refresh_top_bar()
            self._refresh_input()
            self._refresh_status_bar()

    async def _init_claude_md_async(self) -> None:
        from pathlib import Path
        target = Path(self.session.cwd) / "CLAUDE.md"
        if target.exists():
            self._append_to_messages(
                widgets.system_note(f"{target} already exists")
            )
            return
        template = _STARTER_CLAUDE_MD
        try:
            target.write_text(template, encoding="utf-8")
            self.session.read_files.add(str(target.resolve()))
            self._append_to_messages(
                widgets.system_note(f"created {target}")
            )
        except OSError as exc:
            self._append_to_messages(
                widgets.error_panel(f"failed: {exc}")
            )
    def _on_submit(self, e) -> None:
        text = (self.input_field.value or "").strip()
        if not text:
            return
        pending_media = list(getattr(self, "_pending_media", None) or [])
        self._pending_media = []  # type: ignore[attr-defined]
        if self._busy:
            # Queue future steering turns without polluting the transcript.
            self._queued_turns.append((text, pending_media))
            self.input_field.value = ""
            self.input_field.update()
            self._refresh_input()
            self._focus_input()
            return
        self.input_field.value = ""
        self.input_field.update()
        self._submit_turn(text, pending_media)

    def _submit_turn(self, text: str, media_blocks: list[Any] | None = None) -> None:
        media_blocks = list(media_blocks or [])

        # Slash command handling — do not send to the model.
        if text.startswith("/"):
            result = self._dispatcher.dispatch(text, self._build_command_ctx())
            if result is not None and result.handled:
                if result.output:
                    self._hide_welcome()
                    self._append_to_messages(
                        widgets.system_note(result.output)
                    )
                    self._scroll_to_end()
                self._drain_queued_turns()
                return

        self._hide_welcome()
        # Inject system context (cwd + memory) on the first user turn
        if not self.session.messages:
            from ..memory import build_system_context
            from datetime import date
            from ..messages import TextBlock
            ctx = build_system_context(self.session.cwd, date.today().isoformat())
            if ctx.strip():
                self.session.append_message("user", [TextBlock(text=ctx)])
                self.session.append_message("assistant", [TextBlock(text="Acknowledged. Ready to help.")])
        self._append_to_messages(widgets.user_bubble(text, content_width=self._content_width))
        self._stick_to_bottom = True
        self._busy = True
        self._refresh_top_bar(note="thinking…")
        self._refresh_input()
        self._scroll_to_end(force=True)

        try:
            if media_blocks:
                self._current_task = self.page.run_task(self._run_turn_with_media_async, text, media_blocks)
            else:
                self._current_task = self.page.run_task(self._run_turn_async, text)
        except Exception:
            self._busy = False
            self._refresh_top_bar()
            self._refresh_input()
            raise

    def _drain_queued_turns(self) -> None:
        if self._busy or not self._queued_turns:
            self._refresh_input()
            return
        text, media_blocks = self._queued_turns.pop(0)
        self._refresh_input()
        self._submit_turn(text, media_blocks)

    async def _run_turn_with_media_async(self, user_text: str, media_blocks: list) -> None:
        """Like _run_turn_async but first injects image/document blocks on the user message."""
        from ..compaction import compact_messages, should_compact
        from ..messages import TextBlock
        if should_compact(self.session.model_messages):
            self.session.model_messages = await compact_messages(
                self.session.model_messages, self.session.provider
            )
        # Append user message with media + text
        content = list(media_blocks) + [TextBlock(text=user_text)]
        self.session.append_message("user", content)

        # Now run the loop manually (skip the append inside Agent.run_turn by
        # calling a bypass method). Simpler: invoke the agent loop but with
        # an empty user_text — we already appended. Easiest: replicate the loop.
        self._busy = True
        self._refresh_input()
        self._refresh_top_bar(note="thinking…")

        agent = Agent(
            session=self.session,
            system_prompt=self._get_system_prompt(),
            event_sink=self._handle_stream_event,
            permission_cb=self._ask_permission,
        )
        try:
            await agent._drive_loop()  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            self._append_to_messages(
                widgets.error_panel(f"{type(exc).__name__}: {exc}")
            )
        finally:
            self._finalize_streaming_message()
            self._busy = False
            self._refresh_input()
            self._refresh_top_bar()
            self._refresh_status_bar()
            self._autosave()
            self._focus_input()
            self._scroll_to_end()
            self._drain_queued_turns()

    def _append_to_messages(self, widget: ft.Control) -> None:
        """Append widget just above the bottom spacer and flush."""
        self._ensure_message_end_spacer()
        insert_at = max(len(self.message_column.controls) - 1, 0)
        self.message_column.controls.insert(insert_at, widget)
        self._flush_message_column()

    def _extend_messages(self, widgets: list[ft.Control]) -> None:
        if not widgets:
            return
        self._ensure_message_end_spacer()
        insert_at = max(len(self.message_column.controls) - 1, 0)
        self.message_column.controls[insert_at:insert_at] = widgets
        self._flush_message_column()

    def _ensure_message_end_spacer(self) -> None:
        if self._message_end_spacer not in self.message_column.controls:
            self.message_column.controls.append(self._message_end_spacer)

    def _flush_message_column(self) -> None:
        try:
            self.message_column.update()
        except Exception:
            pass

    def _show_thinking(self) -> None:
        self._thinking_widget = None
    def _hide_thinking(self) -> None:
        self._thinking_widget = None


    def _full_update(self) -> None:
        """Full page update - only after replay, clear, or theme change."""
        try:
            self.page.update()
        except Exception:
            pass

    def _scroll_to_end(self, animated: bool = False, force: bool = False) -> None:
        """Scroll to bottom without hijacking the user while reading older content."""
        if not force and not self._stick_to_bottom:
            return
        self._scroll_requested = True
        self._pending_scroll_animated = self._pending_scroll_animated or animated
        if self._scroll_in_flight:
            return
        self._scroll_in_flight = True
        try:
            self.page.run_task(self._scroll_to_end_async)
        except Exception:
            self._scroll_in_flight = False

    async def _scroll_to_end_async(self) -> None:
        try:
            import asyncio
            while self._scroll_requested:
                self._scroll_requested = False
                duration = 180 if self._pending_scroll_animated else 0
                self._pending_scroll_animated = False
                await self.message_column.scroll_to(offset=-1, duration=duration)
                # Flet may settle layout more than once (input shrink, image chips,
                # streaming widget replacement), so follow up with a few forced passes.
                for delay in (0.03, 0.10):
                    await asyncio.sleep(delay)
                    await self.message_column.scroll_to(offset=-1, duration=0)
        except Exception:
            pass
        finally:
            self._scroll_in_flight = False

    def _focus_input(self) -> None:
        """Fire-and-forget focus. `TextField.focus` is async in Flet 0.84."""
        try:
            self.page.run_task(self._focus_input_async)
        except Exception:
            pass

    async def _focus_input_async(self) -> None:
        try:
            await self.input_field.focus()
        except Exception:
            pass

    async def _run_turn_async(self, user_text: str) -> None:
        self._busy = True
        self._refresh_input()
        self._refresh_top_bar(note="thinking…")
        self._show_thinking()

        agent = Agent(
            session=self.session,
            system_prompt=self._get_system_prompt(),
            event_sink=self._handle_stream_event,
            permission_cb=self._ask_permission,
        )
        # Auto-set title from first user message if not yet set
        if not self._current_title:
            self._current_title = user_text[:60]
            self.session.title = self._current_title
            self._refresh_top_bar(note="thinking…")

        try:
            await agent.run_turn(user_text)
        except Exception as exc:  # noqa: BLE001
            self._append_to_messages(
                widgets.error_panel(f"{type(exc).__name__}: {exc}")
            )
        finally:
            self._finalize_streaming_message()
            self._busy = False
            self._current_task = None
            self._refresh_input()
            self._refresh_top_bar()
            self._refresh_status_bar()
            self._autosave()
            self._focus_input()
            self._scroll_to_end()
            self._drain_queued_turns()

    async def _handle_stream_event(self, event: StreamEvent) -> None:
        if isinstance(event, TextDelta):
            self._append_streaming_text(event.text)
        elif isinstance(event, ToolUseStart):
            self._finalize_streaming_message()
        elif isinstance(event, ToolUseEnd):
            self._hide_thinking()
            self._live_tool_entries.append((event.name, event.input, None, False))
            self._update_live_tool_stack()
            self._scroll_to_end()
        elif isinstance(event, ToolResultEvent):
            if self._live_tool_entries:
                name, input_dict, _result_content, _prev_error = self._live_tool_entries[-1]
                self._live_tool_entries[-1] = (name, input_dict, event.content, event.is_error)
                self._update_live_tool_stack()
            else:
                self._append_to_messages(
                    widgets.tool_result_panel(event.content, is_error=event.is_error)
                )
            self._scroll_to_end()
        elif isinstance(event, Usage):
            self._refresh_top_bar(note="thinking…")
        elif isinstance(event, MessageStop):
            self._finalize_streaming_message()
            self._reset_live_tool_stack()

    def _append_streaming_text(self, delta: str) -> None:
        if self._stream_message_widget is None:
            if self._live_tool_entries:
                self._reset_live_tool_stack()
            self._hide_thinking()
            self._stream_text_buf = []
            self._stream_message_widget = widgets.streaming_assistant_message("")
            self._append_to_messages(self._stream_message_widget)
        self._stream_text_buf.append(delta)
        import time
        now = time.monotonic()
        last_flush = getattr(self, "_last_stream_flush", 0.0)
        if now - last_flush >= 0.06 or delta.endswith(("\n", " ", ".", "!", "?", "`")):
            self._last_stream_flush = now
            self._flush_streaming_markdown()
        # Throttled scroll: only scroll every ~400ms during streaming
        last = getattr(self, "_last_stream_scroll", 0.0)
        if now - last > 0.4:
            self._last_stream_scroll = now
            self._scroll_to_end()

    def _flush_streaming_markdown(self) -> None:
        if self._stream_message_widget is None:
            return
        try:
            idx = self.message_column.controls.index(self._stream_message_widget)
        except ValueError:
            return
        try:
            widget = widgets.streaming_assistant_message("".join(self._stream_text_buf))
            self.message_column.controls[idx] = widget
            self._stream_message_widget = widget
            self._flush_message_column()
        except Exception:
            pass

    def _finalize_streaming_message(self) -> None:
        self._hide_thinking()
        if self._stream_message_widget is not None:
            self._flush_streaming_markdown()
            text = "".join(getattr(self, "_stream_text_buf", [])).strip()
            try:
                idx = self.message_column.controls.index(self._stream_message_widget)
            except ValueError:
                idx = -1
            if not text:
                if idx >= 0:
                    self.message_column.controls.pop(idx)
            elif idx >= 0:
                # Replace bare streaming widget with full assistant_message (with retry)
                msg_idx = len(self.session.messages) - 1
                self.message_column.controls[idx] = widgets.assistant_message(
                    text,
                    on_retry=self._on_retry_message,
                    msg_index=msg_idx,
                )
            self._flush_message_column()
            self._stream_message_widget = None
            self._stream_text_buf = []

    def _load_session_data(self, target: CCSessionMeta) -> tuple[list[Any], dict[str, Any]]:
        try:
            stat = target.path.stat()
        except OSError:
            return read_session_jsonl(target.path)

        cached = self._session_cache.get(target.session_id)
        if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
            return list(cached[2]), dict(cached[3])

        messages, metadata = read_session_jsonl(target.path)
        self._session_cache[target.session_id] = (
            stat.st_mtime_ns,
            stat.st_size,
            list(messages),
            dict(metadata),
        )
        return list(messages), dict(metadata)

    def _cache_current_session(self) -> None:
        path = session_jsonl_path(self.session.cwd, self.session.session_id)
        metadata = {
            "session_id": self.session.session_id,
            "title": self.session.title or self._current_title,
            "session_cwd": self.session.cwd,
            "prompt_override": self.session.prompt_override,
            "total_input_tokens": self.session.total_input_tokens,
            "total_output_tokens": self.session.total_output_tokens,
            "last_input_tokens": self.session.last_input_tokens,
            "total_estimated_cost_usd": self.session.total_estimated_cost_usd,
        }
        try:
            stat = path.stat()
        except OSError:
            return
        self._session_cache[self.session.session_id] = (
            stat.st_mtime_ns,
            stat.st_size,
            list(self.session.messages),
            metadata,
        )

    def _build_tool_panel(
        self,
        entries: list[tuple[str, dict[str, Any], str | None, bool]],
    ) -> ft.Control:
        return widgets.tool_turn_panel(entries)

    def _reset_live_tool_stack(self) -> None:
        self._live_tool_entries = []
        self._live_tool_stack_widget = None

    def _update_live_tool_stack(self) -> None:
        if not self._live_tool_entries:
            return
        panel = self._build_tool_panel(self._live_tool_entries)
        if self._live_tool_stack_widget is None:
            self._live_tool_stack_widget = panel
            self._append_to_messages(panel)
            return
        try:
            idx = self.message_column.controls.index(self._live_tool_stack_widget)
        except ValueError:
            self._live_tool_stack_widget = panel
            self._append_to_messages(panel)
            return
        self.message_column.controls[idx] = panel
        self._live_tool_stack_widget = panel
        self._flush_message_column()

    async def _ask_permission(self, tool_name: str, input_dict: dict[str, Any]) -> bool:
        if self._skip_permissions:
            return True
        if (tool_name, "*") in self.session.always_allow:
            return True
        decision = await self.permission_dialog.ask(tool_name, input_dict)
        if decision == "always":
            self.session.always_allow.add((tool_name, "*"))
            return True
        return decision == "allow"

    def _switch_model(self) -> None:
        if self._busy:
            return
        current = self.session.provider.name
        target = "gemini" if current == "anthropic" else "anthropic"
        try:
            new_provider = get_provider(target, self.config)
        except Exception as exc:  # noqa: BLE001
            self._append_to_messages(
                widgets.error_panel(f"can't switch to {target}: {exc}")
            )
            return
        self.session.switch_provider(new_provider)
        self._refresh_top_bar()
        self._refresh_input()
        self._append_to_messages(
            widgets.system_note(f"switched to {target}:{new_provider.model}")
        )
        self._scroll_to_end()

    def _new_chat(self) -> None:
        if self._busy:
            return
        import time
        self.session.messages.clear()
        self.session.model_messages.clear()
        self.session.read_files.clear()
        self.session.always_allow.clear()
        self.session.total_input_tokens = 0
        self.session.total_output_tokens = 0
        self.session.last_input_tokens = 0
        self.session.total_estimated_cost_usd = 0.0
        self.session.session_id = new_session_uuid()
        self.session.created_at = time.time()
        self.session.title = ""
        self._current_title = ""
        self._queued_turns = []
        self._reset_live_tool_stack()
        # New JSONL writer for the new session
        self._jsonl_writer = JsonlSessionWriter(self.session.cwd, self.session.session_id)
        self._jsonl_written_count = 0
        self.message_column.controls.clear()
        self._stream_message_widget = None
        self._welcome_widget = None
        self._show_welcome()
        self._refresh_top_bar()
        self._refresh_status_bar()
        self._refresh_input()
        self._refresh_sidebar()
        self._full_update()
        self._stick_to_bottom = True
        self._remember_current_session()

    def _select_session(self, session_id: str) -> None:
        if self._busy:
            return
        if self.session.session_id == session_id:
            return
        target = next((m for m in self._session_metas if m.session_id == session_id), None)
        if target is None:
            return
        try:
            messages, metadata = self._load_session_data(target)
        except Exception as exc:  # noqa: BLE001
            self._append_to_messages(
                widgets.error_panel(f"failed to load session: {exc}")
            )
            return
        self.session.messages = messages
        self.session.reset_model_messages()
        self.session.read_files.clear()
        self.session.always_allow.clear()
        # Restore persisted state from metadata (includes __meta__ fields)
        self.session.total_input_tokens = metadata.get("total_input_tokens", 0)
        self.session.total_output_tokens = metadata.get("total_output_tokens", 0)
        self.session.last_input_tokens = int(metadata.get("last_input_tokens", 0) or 0)
        self.session.total_estimated_cost_usd = float(
            metadata.get(
                "total_estimated_cost_usd",
                estimate_cost_usd(
                    getattr(self.session.provider, "model", ""),
                    self.session.total_input_tokens,
                    self.session.total_output_tokens,
                ),
            ) or 0.0
        )
        if metadata.get("session_cwd"):
            self.session.cwd = metadata["session_cwd"]
        elif metadata.get("cwd"):
            self.session.cwd = metadata["cwd"]
        self.session.prompt_override = metadata.get("prompt_override", "")
        self.session.session_id = metadata.get("session_id") or session_id
        self.session.title = metadata.get("title") or target.title or ""
        self._current_title = self.session.title or target.title or ""
        self._queued_turns = []
        self._reset_live_tool_stack()
        # Point JSONL writer at the resumed session (append new turns)
        self._jsonl_writer = JsonlSessionWriter(self.session.cwd, self.session.session_id)
        self._jsonl_written_count = len(self.session.messages)
        # Re-render
        self.message_column.controls.clear()
        self._welcome_widget = None
        self._stream_message_widget = None
        if messages:
            self._replay_messages_all()
        else:
            self._show_welcome()
        self._refresh_top_bar()
        self._refresh_status_bar()
        self._refresh_input()
        self._refresh_sidebar()
        self._full_update()
        self._stick_to_bottom = True
        self._remember_current_session()
        self._scroll_to_end(force=True)

    def _delete_session_by_id(self, session_id: str) -> None:
        if self._busy:
            return
        target = next((m for m in self._session_metas if m.session_id == session_id), None)
        if target is None:
            return
        try:
            target.path.unlink()
        except OSError:
            pass
        self._session_cache.pop(session_id, None)
        self._session_metas = [m for m in self._session_metas if m.session_id != session_id]
        if self.session.session_id == session_id:
            self._new_chat()
        else:
            self._refresh_sidebar()

    def _toggle_star(self, session_id: str) -> None:
        target = next((m for m in self._session_metas if m.session_id == session_id), None)
        if target is None:
            return
        new_val = not target.starred
        target.starred = new_val
        set_session_flag(session_id, starred=new_val)
        self._refresh_sidebar()

    def _toggle_hide(self, session_id: str) -> None:
        target = next((m for m in self._session_metas if m.session_id == session_id), None)
        if target is None:
            return
        new_val = not target.hidden
        target.hidden = new_val
        set_session_flag(session_id, hidden=new_val)
        self._refresh_sidebar()

    def _persist_session_snapshot(self, *, rewrite: bool = False) -> None:
        p = session_jsonl_path(self.session.cwd, self.session.session_id)
        if rewrite:
            try:
                p.unlink()
            except OSError:
                pass
            self._session_cache.pop(self.session.session_id, None)
            self._jsonl_writer = JsonlSessionWriter(self.session.cwd, self.session.session_id)
            self._jsonl_written_count = 0

        if not self.session.messages:
            self._session_cache.pop(self.session.session_id, None)
            self._remember_current_session()
            self._refresh_sidebar()
            return

        # Append whichever messages haven't been written yet.
        n_written = getattr(self, "_jsonl_written_count", 0)
        for msg in self.session.messages[n_written:]:
            if msg.role == "user":
                self._jsonl_writer.append_user(msg)
            else:
                self._jsonl_writer.append_assistant(msg)
        self._jsonl_written_count = len(self.session.messages)

        save_session_meta(
            p,
            title=self.session.title or self._current_title or None,
            total_input_tokens=self.session.total_input_tokens,
            total_output_tokens=self.session.total_output_tokens,
            last_input_tokens=self.session.last_input_tokens,
            total_estimated_cost_usd=self.session.total_estimated_cost_usd,
            session_cwd=self.session.cwd,
            prompt_override=self.session.prompt_override or None,
        )
        self._cache_current_session()
        self._remember_current_session()

        import time as _t
        try:
            stat = p.stat()
            mtime = stat.st_mtime
            size = stat.st_size
        except OSError:
            mtime = _t.time()
            size = 0
        found = False
        for i, meta in enumerate(self._session_metas):
            if meta.session_id == self.session.session_id:
                self._session_metas[i] = CCSessionMeta(
                    session_id=meta.session_id,
                    path=meta.path,
                    cwd=self.session.cwd,
                    mtime=mtime,
                    size=size,
                    title=self._current_title or meta.title,
                    starred=meta.starred,
                    hidden=meta.hidden,
                )
                found = True
                break
        if not found:
            self._session_metas.insert(
                0,
                CCSessionMeta(
                    session_id=self.session.session_id,
                    path=p,
                    cwd=self.session.cwd,
                    mtime=mtime,
                    size=size,
                    title=self._current_title or "",
                ),
            )
        self._refresh_sidebar()

    def _autosave(self) -> None:
        """Append the last turn (user + assistant) to the JSONL session file."""
        if not self.session.messages:
            return
        try:
            rewrite = getattr(self, "_jsonl_written_count", 0) > len(self.session.messages)
            self._persist_session_snapshot(rewrite=rewrite)
        except Exception:
            pass

    def _remove_attachment(self, idx: int) -> None:
        pending = getattr(self, "_pending_media", None) or []
        if 0 <= idx < len(pending):
            pending.pop(idx)
            self._pending_media = pending
        self._refresh_input()

    def _remove_queued_turn(self, idx: int) -> None:
        if 0 <= idx < len(self._queued_turns):
            self._queued_turns.pop(idx)
        self._refresh_input()

    def _on_attach(self) -> None:
        self.page.run_task(self._on_attach_async)

    async def _on_attach_async(self) -> None:
        files = await self._file_picker.pick_files(allow_multiple=True)
        if not files:
            return
        self._process_picked_files(files)

    def _process_picked_files(self, files: list) -> None:
        import base64
        from pathlib import Path
        from ..messages import DocumentBlock, ImageBlock

        text_blocks: list[str] = []
        pending_media: list = []  # (ImageBlock|DocumentBlock, filename)

        for f in files:
            try:
                p = Path(f.path) if f.path else None
                if p is None or not p.exists():
                    continue
                ext = p.suffix.lower().lstrip(".")
                size = p.stat().st_size

                # Image?
                image_exts = {"png", "jpg", "jpeg", "gif", "webp"}
                if ext in image_exts:
                    if size > 10 * 1024 * 1024:
                        text_blocks.append(f"[{p.name} skipped: >10MB image]")
                        continue
                    raw = p.read_bytes()
                    media_type = f"image/{ext if ext != 'jpg' else 'jpeg'}"
                    pending_media.append(
                        (ImageBlock(data_base64=base64.b64encode(raw).decode(), media_type=media_type), p.name)
                    )
                    continue

                # PDF?
                if ext == "pdf":
                    if size > 20 * 1024 * 1024:
                        text_blocks.append(f"[{p.name} skipped: >20MB pdf]")
                        continue
                    raw = p.read_bytes()
                    pending_media.append(
                        (DocumentBlock(data_base64=base64.b64encode(raw).decode()), p.name)
                    )
                    continue

                # Text fallback
                if size > 500_000:
                    text_blocks.append(f"[{p.name} skipped: >500KB]")
                    continue
                content = p.read_text(encoding="utf-8", errors="replace")
                if len(content) > 50_000:
                    content = content[:50_000] + "\n…(truncated)"
                text_blocks.append(f"### {p}\n\n```\n{content}\n```")
                self.session.read_files.add(str(p.resolve()))
            except Exception as exc:  # noqa: BLE001
                text_blocks.append(f"[error attaching {f.name}: {exc}]")

        # Queue media for the NEXT submit (stored until _on_submit)
        if pending_media:
            if not hasattr(self, "_pending_media"):
                self._pending_media = []  # type: ignore[attr-defined]
            for block, name in pending_media:
                self._pending_media.append(block)  # type: ignore[attr-defined]

        if text_blocks:
            current = self.input_field.value or ""
            # Only add non-attachment text (file contents)
            file_texts = [t for t in text_blocks if not t.startswith("[attached:")]
            if file_texts:
                header = "\n\n".join(file_texts)
                self.input_field.value = f"{header}\n\n{current}"
                self.input_field.update()
        self._refresh_input()
        self._focus_input()


_STARTER_CLAUDE_MD = """# Project memory

This file is automatically loaded by openh when it starts a session in this
directory or any subdirectory. Add project-specific guidance for the assistant
here — build commands, code style rules, architectural conventions, known
caveats, etc.

## Build & test commands
- How to run tests:
- How to run the linter/typechecker:
- How to start the dev server:

## Code style
- (note any unusual conventions here)

## Architecture
- (high-level map of important modules)

## Known issues / gotchas
- (things the assistant should watch out for)
"""


def main() -> None:
    def target(page: ft.Page) -> None:
        OpenHApp(page)

    ft.app(target=target)


if __name__ == "__main__":
    main()
