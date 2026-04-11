"""Settings dialog — runtime configuration UI.

Sections:
  1. Models (dropdowns for Anthropic + Gemini)
  2. API keys (masked fields; writes to /Users/hyeon/Projects/.env)
  3. Tokens (max_output_tokens, auto_compact_threshold)
  4. Agents (subagent_parallel)
  5. System prompt (preset dropdown + editor + save-as)
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from .. import prompts, settings as settings_mod
from ..settings import ANTHROPIC_MODELS, GEMINI_MODELS, Settings
from . import theme


class SettingsDialog:
    def __init__(
        self,
        page: ft.Page,
        current: Settings,
        on_save: Callable[[Settings], None],
        session: "Any | None" = None,
    ) -> None:
        self.page = page
        self.settings = Settings(**{k: getattr(current, k) for k in current.__dataclass_fields__})
        self.on_save = on_save
        self._session = session
        self.dialog: ft.AlertDialog | None = None
        self._env_path = Path("/Users/hyeon/Projects/.env")

        # Prompt editor state
        self._presets = prompts.list_presets()
        self._active_preset_name = current.active_prompt
        self._prompt_dirty = False
        self._prompt_new_name: str = ""

    # ------------------------------------------------------------------ open

    def open(self) -> None:
        self.dialog = ft.AlertDialog(
            modal=True,
            bgcolor=theme.BG_ELEVATED,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.SETTINGS_OUTLINED, color=theme.ACCENT, size=20),
                    ft.Text(
                        "Settings",
                        color=theme.TEXT_PRIMARY,
                        size=18,
                        weight=ft.FontWeight.W_700,
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            content=ft.Container(
                width=780,
                height=560,
                content=self._build_tabs(),
            ),
            actions=[
                ft.TextButton(
                    content=ft.Text("Cancel", color=theme.TEXT_SECONDARY, size=13),
                    on_click=self._on_cancel,
                ),
                ft.FilledButton(
                    content=ft.Text(
                        "Save",
                        color=theme.TEXT_ON_ACCENT,
                        size=13,
                        weight=ft.FontWeight.W_600,
                    ),
                    on_click=self._on_save_click,
                    style=ft.ButtonStyle(
                        bgcolor=theme.ACCENT,
                        color=theme.TEXT_ON_ACCENT,
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.show_dialog(self.dialog)

    def _close(self) -> None:
        if self.dialog is not None:
            try:
                self.page.pop_dialog()
            except Exception:
                pass
            self.dialog = None

    def _on_cancel(self, e) -> None:
        self._close()

    def _on_save_click(self, e) -> None:
        self._commit_general_fields()
        try:
            self.on_save(self.settings)
        finally:
            self._close()

    # --------------------------------------------------------------- layout

    def _build_tabs(self) -> ft.Control:
        """Custom left-rail category list + right body panel."""
        self._categories = [
            ("Models", self._tab_models),
            ("API keys", self._tab_keys),
            ("Appearance", self._tab_appearance),
            ("Tokens", self._tab_tokens),
            ("Agents", self._tab_agents),
            ("Prompt", self._tab_prompt),
            ("Workspace", self._tab_workspace),
        ]
        self._current_category = 0

        # Build all bodies ONCE and cache so field state survives tab switches.
        self._cached_bodies: list[ft.Control] = [b() for _, b in self._categories]

        self._body_holder = ft.Container(
            content=self._cached_bodies[0],
            expand=True,
        )

        def make_cat_item(idx: int, name: str) -> ft.Container:
            def _on_click(e, i=idx):
                self._switch_category(i)
            return ft.Container(
                content=ft.Text(
                    name,
                    color=theme.TEXT_PRIMARY if idx == self._current_category else theme.TEXT_SECONDARY,
                    size=13,
                    weight=ft.FontWeight.W_600 if idx == self._current_category else ft.FontWeight.W_400,
                ),
                padding=ft.padding.symmetric(horizontal=14, vertical=10),
                margin=ft.margin.symmetric(horizontal=4, vertical=1),
                bgcolor=theme.BG_SIDEBAR_SELECTED if idx == self._current_category else None,
                border_radius=theme.RADIUS_SM,
                on_click=_on_click,
                ink=True,
            )

        self._cat_items = [make_cat_item(i, name) for i, (name, _) in enumerate(self._categories)]

        rail = ft.Container(
            content=ft.Column(self._cat_items, spacing=0, tight=True),
            width=150,
            bgcolor=theme.BG_SIDEBAR,
            padding=ft.padding.symmetric(vertical=8),
            border=ft.border.only(right=ft.BorderSide(1, theme.BORDER_FAINT)),
        )

        return ft.Row(
            [rail, self._body_holder],
            spacing=0,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def _switch_category(self, idx: int) -> None:
        if idx == self._current_category:
            return
        self._current_category = idx
        # Update rail highlighting
        for i, item in enumerate(self._cat_items):
            text: ft.Text = item.content  # type: ignore[assignment]
            text.color = theme.TEXT_PRIMARY if i == idx else theme.TEXT_SECONDARY
            text.weight = ft.FontWeight.W_600 if i == idx else ft.FontWeight.W_400
            item.bgcolor = theme.BG_SIDEBAR_SELECTED if i == idx else None
            try:
                item.update()
            except Exception:
                pass
        # Swap body to the cached instance (preserves field values)
        self._body_holder.content = self._cached_bodies[idx]
        try:
            self._body_holder.update()
        except Exception:
            pass

    # --------------------------------------------------------------- tab 1

    def _tab_models(self) -> ft.Control:
        self._provider_radio = ft.RadioGroup(
            value=self.settings.active_provider,
            content=ft.Row(
                [
                    ft.Radio(value="anthropic", label="Anthropic"),
                    ft.Radio(value="gemini", label="Gemini"),
                ],
                spacing=16,
            ),
        )

        self._anth_dropdown = ft.Dropdown(
            value=self.settings.anthropic_model,
            options=[ft.dropdown.Option(m) for m in ANTHROPIC_MODELS],
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            label="Anthropic model",
            expand=True,
        )

        self._gem_dropdown = ft.Dropdown(
            value=self.settings.gemini_model,
            options=[ft.dropdown.Option(m) for m in GEMINI_MODELS],
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            label="Gemini model",
            expand=True,
        )

        return _padded_column(
            [
                _label("Active provider"),
                self._provider_radio,
                ft.Container(height=12),
                self._anth_dropdown,
                ft.Container(height=12),
                self._gem_dropdown,
                ft.Container(height=16),
                _hint(
                    "Provider can also be toggled at runtime with ⌘M or the "
                    "model dropdown in the input area."
                ),
            ]
        )

    # --------------------------------------------------------------- tab 2

    def _tab_keys(self) -> ft.Control:
        import os

        anth_key = os.environ.get("ANTHROPIC_API_KEY", "")
        gem_key = os.environ.get("GEMINI_API_KEY", "")

        self._anth_key_field = ft.TextField(
            value=anth_key,
            password=True,
            can_reveal_password=True,
            label="ANTHROPIC_API_KEY",
            hint_text="sk-ant-api03-…",
            border_color=theme.BORDER_SUBTLE,
            cursor_color=theme.ACCENT,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=12, font_family=theme.FONT_MONO),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            hint_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=11),
        )
        self._gem_key_field = ft.TextField(
            value=gem_key,
            password=True,
            can_reveal_password=True,
            label="GEMINI_API_KEY",
            hint_text="AIzaSy…",
            border_color=theme.BORDER_SUBTLE,
            cursor_color=theme.ACCENT,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=12, font_family=theme.FONT_MONO),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            hint_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=11),
        )

        status_anth = ("●  ANTHROPIC_API_KEY is currently set" if anth_key
                       else "○  ANTHROPIC_API_KEY is NOT set")
        status_gem = ("●  GEMINI_API_KEY is currently set" if gem_key
                      else "○  GEMINI_API_KEY is NOT set")

        return _padded_column(
            [
                _label("API keys"),
                ft.Text(status_anth, color=theme.SUCCESS if anth_key else theme.WARN, size=11),
                ft.Text(status_gem, color=theme.SUCCESS if gem_key else theme.WARN, size=11),
                ft.Container(height=10),
                self._anth_key_field,
                ft.Container(height=10),
                self._gem_key_field,
                ft.Container(height=14),
                _hint(
                    f"Keys are written to {self._env_path}. "
                    "Blank fields are ignored — only non-empty values overwrite. "
                    "Restart the app after saving to pick up new keys."
                ),
            ]
        )

    # --------------------------------------------------------------- tab 3

    def _tab_tokens(self) -> ft.Control:
        self._max_tokens_field = ft.TextField(
            value=str(self.settings.max_output_tokens),
            label="Max output tokens per turn",
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self._compact_field = ft.TextField(
            value=str(self.settings.auto_compact_threshold),
            label="Auto-compact threshold (tokens)",
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        return _padded_column(
            [
                _label("Token budgets"),
                self._max_tokens_field,
                ft.Container(height=10),
                self._compact_field,
                ft.Container(height=14),
                _hint(
                    "Auto-compact triggers when the conversation exceeds this "
                    "rough character-based estimate. Old turns are summarized "
                    "into a single message, keeping the last ~6 turns verbatim."
                ),
            ]
        )

    # --------------------------------------------------------------- tab 4

    def _tab_agents(self) -> ft.Control:
        self._subagent_field = ft.TextField(
            value=str(self.settings.subagent_parallel),
            label="Sub-agents parallel",
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self._skip_perms_toggle = ft.Switch(
            value=self.settings.skip_permissions,
            label="Skip all permission prompts",
            active_color=theme.ACCENT,
            label_text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
        )
        return _padded_column(
            [
                _label("Sub-agents"),
                self._subagent_field,
                ft.Container(height=14),
                _hint(
                    "When the model calls the Agent tool, this controls how "
                    "many sub-agents can run concurrently. 1 = strictly sequential."
                ),
                ft.Container(height=18),
                _label("Danger zone"),
                self._skip_perms_toggle,
                ft.Container(height=8),
                _hint(
                    "When ON, Write / Edit / Bash / Agent run without the "
                    "per-call confirmation modal. Claude Code's --dangerously-skip-permissions."
                ),
            ]
        )

    # --------------------------------------------------------------- tab 6

    def _tab_appearance(self) -> ft.Control:
        from . import theme as theme_mod

        color_names = list(theme_mod.COLOR_PRESETS.keys())
        font_names = list(theme_mod.FONT_PRESETS.keys())

        # Build color swatch tiles
        self._color_tiles: list[ft.Container] = []
        for name in color_names:
            dark_tok, light_tok = theme_mod.COLOR_PRESETS[name]
            selected = name == self.settings.color_preset

            def make_tile(n=name):
                dk, lt = theme_mod.COLOR_PRESETS[n]
                sel = n == self.settings.color_preset
                return ft.Container(
                    content=ft.Column([
                        ft.Row([
                            ft.Container(width=14, height=14, border_radius=7, bgcolor=dk.BG_PAGE),
                            ft.Container(width=14, height=14, border_radius=7, bgcolor=dk.ACCENT),
                            ft.Container(width=14, height=14, border_radius=7, bgcolor=lt.BG_PAGE),
                            ft.Container(width=14, height=14, border_radius=7, bgcolor=lt.ACCENT),
                        ], spacing=3, tight=True),
                        ft.Text(n, color=theme.TEXT_PRIMARY if sel else theme.TEXT_SECONDARY, size=11,
                                weight=ft.FontWeight.W_600 if sel else ft.FontWeight.W_400),
                    ], spacing=4, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                    padding=ft.padding.all(8),
                    border_radius=theme.RADIUS_SM,
                    border=ft.border.all(2, theme.ACCENT if sel else theme.BORDER_FAINT),
                    bgcolor=theme.BG_HOVER if sel else None,
                    on_click=lambda e, nm=n: self._select_color_preset(nm),
                    ink=True,
                    width=110,
                )
            self._color_tiles.append(make_tile())

        color_grid = ft.Row(
            self._color_tiles, wrap=True, spacing=8, run_spacing=8,
        )

        font_dropdown = ft.Dropdown(
            value=self.settings.font_preset,
            options=[ft.dropdown.Option(n) for n in font_names],
            width=250,
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            on_select=lambda e: setattr(self.settings, "font_preset", e.control.value),
        )

        return _padded_column(
            [
                _label("Color theme"),
                ft.Text(
                    "Select a palette. Applied on save.",
                    color=theme.TEXT_TERTIARY, size=11, italic=True,
                ),
                ft.Container(height=8),
                color_grid,
                ft.Container(height=16),
                _label("Font"),
                font_dropdown,
                ft.Container(height=8),
                ft.Text(
                    "Tip: toggle light/dark (top bar icon) to see both variants.",
                    color=theme.TEXT_TERTIARY, size=10,
                ),
            ]
        )

    def _select_color_preset(self, name: str) -> None:
        self.settings.color_preset = name
        # Rebuild the tiles to update selection highlight
        from . import theme as theme_mod
        for i, tile_name in enumerate(theme_mod.COLOR_PRESETS.keys()):
            sel = tile_name == name
            tile = self._color_tiles[i]
            tile.border = ft.border.all(2, theme.ACCENT if sel else theme.BORDER_FAINT)
            tile.bgcolor = theme.BG_HOVER if sel else None
            # Update the label weight
            col = tile.content
            if isinstance(col, ft.Column) and len(col.controls) > 1:
                label = col.controls[1]
                if isinstance(label, ft.Text):
                    label.color = theme.TEXT_PRIMARY if sel else theme.TEXT_SECONDARY
                    label.weight = ft.FontWeight.W_600 if sel else ft.FontWeight.W_400
        try:
            for t in self._color_tiles:
                t.update()
        except Exception:
            pass

    def _tab_workspace(self) -> ft.Control:
        import os
        current_cwd = self._session.cwd if self._session else os.getcwd()

        self._cwd_label = ft.Text(
            current_cwd,
            color=theme.TEXT_PRIMARY,
            size=12,
            font_family=theme.FONT_MONO,
            selectable=True,
        )

        self._folder_picker = ft.FilePicker()

        async def _pick_folder(e):
            if self._folder_picker not in self.page.services:
                self.page.services.append(self._folder_picker)
                self.page.update()
            result = await self._folder_picker.get_directory_path(dialog_title="Select workspace")
            if result:
                os.chdir(result)
                if self._session:
                    self._session.cwd = result
                self._cwd_label.value = result
                self._cwd_label.update()

        change_btn = ft.ElevatedButton(
            "Change folder…",
            icon=ft.Icons.FOLDER_OPEN,
            on_click=lambda e: self.page.run_task(lambda: _pick_folder(e)),
            style=ft.ButtonStyle(
                bgcolor=theme.BG_ELEVATED,
                color=theme.TEXT_PRIMARY,
            ),
        )

        return _padded_column(
            [
                _label("Working directory (this session)"),
                ft.Container(
                    content=self._cwd_label,
                    bgcolor=theme.BG_DEEPEST,
                    padding=ft.padding.all(10),
                    border_radius=theme.RADIUS_SM,
                    border=ft.border.all(1, theme.BORDER_SUBTLE),
                ),
                ft.Container(height=8),
                change_btn,
                ft.Container(height=12),
                ft.Text(
                    "Changes the working directory for this session. "
                    "Tools (Bash, Read, etc.) will operate relative to this path. "
                    "CLAUDE.md is reloaded from the new directory.",
                    color=theme.TEXT_TERTIARY,
                    size=11,
                    italic=True,
                ),
            ]
        )

    # --------------------------------------------------------------- tab 5

    def _tab_prompt(self) -> ft.Control:
        # Preset dropdown
        self._preset_dropdown = ft.Dropdown(
            value=self._active_preset_name,
            options=[ft.dropdown.Option(p.name) for p in self._presets],
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            label="Active preset",
            on_select=self._on_preset_change,
            expand=True,
        )

        # Editor
        initial = prompts.resolve_active(self._active_preset_name)
        self._prompt_editor = ft.TextField(
            value=initial,
            multiline=True,
            min_lines=12,
            max_lines=18,
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(
                color=theme.TEXT_PRIMARY,
                size=12,
                font_family=theme.FONT_MONO,
            ),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            label="System prompt",
            read_only=self._is_builtin_selected(),
            on_change=self._on_editor_change,
        )

        # Name input (for save-as)
        self._name_field = ft.TextField(
            value="",
            label="New preset name (optional)",
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=12),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            expand=True,
        )

        self._prompt_feedback = ft.Text("", color=theme.TEXT_TERTIARY, size=11, italic=True)

        def _btn_text(label: str, color: str) -> ft.Text:
            return ft.Text(label, color=color, size=12, weight=ft.FontWeight.W_500)

        new_btn = ft.FilledTonalButton(
            content=_btn_text("New blank", theme.TEXT_PRIMARY),
            icon=ft.Icons.ADD,
            on_click=self._on_new_blank,
            style=ft.ButtonStyle(bgcolor=theme.BG_HOVER),
        )
        copy_btn = ft.FilledTonalButton(
            content=_btn_text("Copy to new", theme.TEXT_PRIMARY),
            icon=ft.Icons.COPY,
            on_click=self._on_copy_to_new,
            style=ft.ButtonStyle(bgcolor=theme.BG_HOVER),
        )
        save_btn = ft.FilledButton(
            content=_btn_text("Save preset", theme.TEXT_ON_ACCENT),
            icon=ft.Icons.SAVE,
            on_click=self._on_save_preset,
            style=ft.ButtonStyle(bgcolor=theme.ACCENT, color=theme.TEXT_ON_ACCENT),
        )
        delete_btn = ft.OutlinedButton(
            content=_btn_text("Delete", theme.ERROR),
            icon=ft.Icons.DELETE_OUTLINE,
            on_click=self._on_delete_preset,
        )

        return _padded_column(
            [
                self._preset_dropdown,
                ft.Container(height=10),
                self._prompt_editor,
                ft.Container(height=10),
                self._name_field,
                ft.Container(height=8),
                ft.Row(
                    [new_btn, copy_btn, save_btn, ft.Container(expand=True), delete_btn],
                    spacing=8,
                ),
                ft.Container(height=4),
                self._prompt_feedback,
                _hint(
                    "The 'default' preset is built-in and cannot be deleted or "
                    "overwritten. Use 'New blank' to start from scratch, or "
                    "'Copy to new' to start from the current preset."
                ),
            ]
        )

    # ----------------- prompt tab helpers

    def _is_builtin_selected(self) -> bool:
        return (self._active_preset_name or "").lower() == prompts.BUILTIN_NAME

    def _on_preset_change(self, e) -> None:
        name = self._preset_dropdown.value or prompts.BUILTIN_NAME
        self._active_preset_name = name
        self._prompt_editor.value = prompts.resolve_active(name)
        self._prompt_editor.read_only = self._is_builtin_selected()
        self._prompt_dirty = False
        self._name_field.value = ""
        self._prompt_feedback.value = ""
        try:
            self._prompt_editor.update()
            self._name_field.update()
            self._prompt_feedback.update()
        except Exception:
            pass

    def _on_editor_change(self, e) -> None:
        self._prompt_dirty = True

    def _on_new_blank(self, e) -> None:
        self._prompt_editor.value = ""
        self._prompt_editor.read_only = False
        self._active_preset_name = ""
        self._preset_dropdown.value = None
        self._name_field.value = ""
        self._prompt_feedback.value = "Start typing a new preset, then enter a name and click Save."
        try:
            self._prompt_editor.update()
            self._preset_dropdown.update()
            self._name_field.update()
            self._prompt_feedback.update()
        except Exception:
            pass

    def _on_copy_to_new(self, e) -> None:
        # Keep the current text, but switch out of read-only + clear active selection
        self._prompt_editor.read_only = False
        base_name = self._active_preset_name or "copy"
        self._name_field.value = f"{base_name}-copy"
        self._active_preset_name = ""
        self._preset_dropdown.value = None
        self._prompt_feedback.value = "Edit freely and Save under a new name."
        try:
            self._prompt_editor.update()
            self._preset_dropdown.update()
            self._name_field.update()
            self._prompt_feedback.update()
        except Exception:
            pass

    def _on_save_preset(self, e) -> None:
        text = self._prompt_editor.value or ""
        # Determine save target
        name = (self._name_field.value or "").strip()
        if not name:
            # If editing a non-builtin preset with no new name, overwrite it
            if self._active_preset_name and not self._is_builtin_selected():
                name = self._active_preset_name
            else:
                self._prompt_feedback.value = "Enter a name to save as a new preset."
                try:
                    self._prompt_feedback.update()
                except Exception:
                    pass
                return
        try:
            preset = prompts.save_preset(name, text)
        except ValueError as exc:
            self._prompt_feedback.value = f"error: {exc}"
            try:
                self._prompt_feedback.update()
            except Exception:
                pass
            return
        # Refresh dropdown
        self._presets = prompts.list_presets()
        self._preset_dropdown.options = [ft.dropdown.Option(p.name) for p in self._presets]
        self._preset_dropdown.value = preset.name
        self._active_preset_name = preset.name
        self.settings.active_prompt = preset.name
        self._prompt_dirty = False
        self._name_field.value = ""
        self._prompt_feedback.value = f"Saved as '{preset.name}'."
        try:
            self._preset_dropdown.update()
            self._name_field.update()
            self._prompt_feedback.update()
        except Exception:
            pass

    def _on_delete_preset(self, e) -> None:
        if self._is_builtin_selected():
            self._prompt_feedback.value = "Cannot delete the built-in 'default' preset."
            try:
                self._prompt_feedback.update()
            except Exception:
                pass
            return
        if not self._active_preset_name:
            return
        try:
            prompts.delete_preset(self._active_preset_name)
        except ValueError as exc:
            self._prompt_feedback.value = f"error: {exc}"
            try:
                self._prompt_feedback.update()
            except Exception:
                pass
            return
        self._presets = prompts.list_presets()
        self._preset_dropdown.options = [ft.dropdown.Option(p.name) for p in self._presets]
        self._preset_dropdown.value = prompts.BUILTIN_NAME
        self._active_preset_name = prompts.BUILTIN_NAME
        self.settings.active_prompt = prompts.BUILTIN_NAME
        self._prompt_editor.value = prompts.resolve_active(prompts.BUILTIN_NAME)
        self._prompt_editor.read_only = True
        self._prompt_feedback.value = "Deleted."
        try:
            self._preset_dropdown.update()
            self._prompt_editor.update()
            self._prompt_feedback.update()
        except Exception:
            pass

    # --------------------------------------------------------- commit

    def _commit_general_fields(self) -> None:
        self.settings.active_provider = self._provider_radio.value or "anthropic"
        self.settings.anthropic_model = self._anth_dropdown.value or self.settings.anthropic_model
        self.settings.gemini_model = self._gem_dropdown.value or self.settings.gemini_model

        try:
            self.settings.max_output_tokens = int(self._max_tokens_field.value or 0) or 8192
        except ValueError:
            pass
        try:
            self.settings.auto_compact_threshold = int(self._compact_field.value or 0) or 80_000
        except ValueError:
            pass
        try:
            self.settings.subagent_parallel = max(1, int(self._subagent_field.value or 1))
        except ValueError:
            self.settings.subagent_parallel = 1
        self.settings.skip_permissions = bool(self._skip_perms_toggle.value)

        # Persist API keys to .env
        try:
            self._persist_keys(
                self._anth_key_field.value or "",
                self._gem_key_field.value or "",
            )
        except Exception:
            pass

    def _persist_keys(self, anth: str, gem: str) -> None:
        """Upsert ANTHROPIC_API_KEY / GEMINI_API_KEY into the .env file.

        SAFETY: empty values are NEVER written. If the user leaves a field blank,
        the existing value in .env is preserved. This prevents accidental
        destruction of secrets when the dialog is saved without touching them.
        """
        anth = (anth or "").strip()
        gem = (gem or "").strip()
        if not anth and not gem:
            return  # nothing to do
        if not self._env_path.exists():
            self._env_path.parent.mkdir(parents=True, exist_ok=True)
            self._env_path.touch()
        lines = self._env_path.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        seen_anth = False
        seen_gem = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("ANTHROPIC_API_KEY="):
                if anth:
                    out.append(f"ANTHROPIC_API_KEY={anth}")
                else:
                    out.append(line)  # keep existing
                seen_anth = True
            elif stripped.startswith("GEMINI_API_KEY="):
                if gem:
                    out.append(f"GEMINI_API_KEY={gem}")
                else:
                    out.append(line)  # keep existing
                seen_gem = True
            else:
                out.append(line)
        if not seen_anth and anth:
            out.append(f"ANTHROPIC_API_KEY={anth}")
        if not seen_gem and gem:
            out.append(f"GEMINI_API_KEY={gem}")
        self._env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _padded_column(children: list[ft.Control]) -> ft.Control:
    return ft.Container(
        content=ft.Column(children, spacing=0, scroll=ft.ScrollMode.AUTO, tight=False),
        padding=ft.padding.only(top=16, left=18, right=18, bottom=16),
        expand=True,
    )


def _label(text: str) -> ft.Control:
    return ft.Container(
        content=ft.Text(
            text,
            color=theme.TEXT_TERTIARY,
            size=11,
            weight=ft.FontWeight.W_700,
        ),
        padding=ft.padding.only(bottom=8),
    )


def _hint(text: str) -> ft.Control:
    return ft.Text(
        text,
        color=theme.TEXT_TERTIARY,
        size=11,
        italic=True,
    )
