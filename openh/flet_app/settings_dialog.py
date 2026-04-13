"""Settings dialog — runtime configuration UI.

Sections:
  1. Models (dropdowns for OpenAI + Anthropic + Gemini)
  2. API keys (masked fields; reads repo .env + ~/.openh/.env)
  3. Tokens (max_output_tokens, auto_compact_threshold)
  4. Agents (subagent_parallel)
  5. System prompt (preset dropdown + editor + save-as)
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import flet as ft

from ..config import (
    LEGACY_DOTENV_PATH,
    REPO_DOTENV_PATH,
    USER_DOTENV_PATH,
    load_env_files,
    preferred_dotenv_path,
)
from .. import output_styles, prompts, settings as settings_mod
from ..settings import (
    ANTHROPIC_MODELS,
    GEMINI_MODELS,
    GEMINI_THINKING_EFFORTS,
    OPENAI_MODELS,
    Settings,
)
from ..session import normalize_usage_by_model
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
        self.settings = settings_mod.normalize_settings(
            Settings(**{k: getattr(current, k) for k in current.__dataclass_fields__})
        )
        self.on_save = on_save
        self._session = session
        self.dialog: ft.AlertDialog | None = None
        self._env_path = preferred_dotenv_path()
        self._env_read_paths = tuple(
            dict.fromkeys((REPO_DOTENV_PATH, LEGACY_DOTENV_PATH, USER_DOTENV_PATH))
        )

        # Prompt editor state
        self._presets = prompts.list_presets()
        active = prompts.get_preset(current.active_prompt) if current.active_prompt else None
        self._active_preset_name = active.slug if active else prompts.BUILTIN_NAME
        self._default_preset_name = self._active_preset_name or prompts.BUILTIN_NAME
        self._prompt_dirty = False
        self._prompt_new_name: str = ""

    def _preset_label(self, preset_name: str | None) -> str:
        target = str(preset_name or "").strip()
        if not target:
            return prompts.BUILTIN_NAME
        preset = prompts.get_preset(target)
        return preset.name if preset is not None else target

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
            ("Identity", self._tab_identity),
            ("Tokens", self._tab_tokens),
            ("Agents", self._tab_agents),
            ("Prompt", self._tab_prompt),
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
        def _model_options(models: list[str], current: str) -> list[ft.dropdown.Option]:
            ordered: list[str] = []
            current_value = str(current or "").strip()
            if current_value and current_value not in models:
                ordered.append(current_value)
            ordered.extend(models)
            seen: set[str] = set()
            result: list[ft.dropdown.Option] = []
            for model in ordered:
                if model in seen:
                    continue
                seen.add(model)
                result.append(ft.dropdown.Option(model))
            return result

        self._provider_radio = ft.RadioGroup(
            value=self.settings.active_provider,
            content=ft.Row(
                [
                    ft.Radio(value="openai", label="OpenAI"),
                    ft.Radio(value="anthropic", label="Anthropic"),
                    ft.Radio(value="gemini", label="Gemini"),
                ],
                spacing=16,
            ),
        )

        self._openai_dropdown = ft.Dropdown(
            value=self.settings.openai_model,
            options=_model_options(OPENAI_MODELS, self.settings.openai_model),
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            label="OpenAI model",
            expand=True,
        )

        self._anth_dropdown = ft.Dropdown(
            value=self.settings.anthropic_model,
            options=_model_options(ANTHROPIC_MODELS, self.settings.anthropic_model),
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            label="Anthropic model",
            expand=True,
        )

        self._gem_dropdown = ft.Dropdown(
            value=self.settings.gemini_model,
            options=_model_options(GEMINI_MODELS, self.settings.gemini_model),
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
                self._openai_dropdown,
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

        load_env_files()
        openai_key = os.environ.get("OPENAI_API_KEY", "")
        anth_key = os.environ.get("ANTHROPIC_API_KEY", "")
        gem_key = os.environ.get("GEMINI_API_KEY", "")

        self._openai_key_field = ft.TextField(
            value=openai_key,
            password=True,
            can_reveal_password=True,
            label="OPENAI_API_KEY",
            hint_text="sk-proj-…",
            border_color=theme.BORDER_SUBTLE,
            cursor_color=theme.ACCENT,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=12, font_family=theme.FONT_MONO),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            hint_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=11),
        )
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

        status_openai = ("●  OPENAI_API_KEY is currently set" if openai_key
                         else "○  OPENAI_API_KEY is NOT set")
        status_anth = ("●  ANTHROPIC_API_KEY is currently set" if anth_key
                       else "○  ANTHROPIC_API_KEY is NOT set")
        status_gem = ("●  GEMINI_API_KEY is currently set" if gem_key
                      else "○  GEMINI_API_KEY is NOT set")

        return _padded_column(
            [
                _label("API keys"),
                ft.Text(status_openai, color=theme.SUCCESS if openai_key else theme.WARN, size=11),
                ft.Text(status_anth, color=theme.SUCCESS if anth_key else theme.WARN, size=11),
                ft.Text(status_gem, color=theme.SUCCESS if gem_key else theme.WARN, size=11),
                ft.Container(height=10),
                self._openai_key_field,
                ft.Container(height=10),
                self._anth_key_field,
                ft.Container(height=10),
                self._gem_key_field,
                ft.Container(height=14),
                _hint(
                    "Keys are read from "
                    + ", ".join(str(path) for path in self._env_read_paths)
                    + f". Saving writes to {self._env_path}. "
                    + "Blank fields are ignored — only non-empty values overwrite, "
                    + "and new keys apply right away."
                ),
            ]
        )

    # --------------------------------------------------------------- tab 3

    def _tab_identity(self) -> ft.Control:
        self._user_profile_toggle = ft.Switch(
            value=bool(getattr(self.settings, "user_profile_enabled", False)),
            label="Apply global user profile",
            active_color=theme.ACCENT,
            label_text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
        )
        self._user_profile_field = ft.TextField(
            value=str(getattr(self.settings, "user_profile_text", "") or ""),
            multiline=True,
            min_lines=4,
            max_lines=7,
            label="Who I am / how I work",
            hint_text="내가 누군지, 주로 뭘 하는지, 답변 선호, 금지사항…",
            border_color=theme.BORDER_SUBTLE,
            cursor_color=theme.ACCENT,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=12),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            hint_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=11),
        )
        self._agent_persona_toggle = ft.Switch(
            value=bool(getattr(self.settings, "agent_persona_enabled", False)),
            label="Apply global agent persona",
            active_color=theme.ACCENT,
            label_text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
        )
        self._agent_persona_field = ft.TextField(
            value=str(getattr(self.settings, "agent_persona_text", "") or ""),
            multiline=True,
            min_lines=4,
            max_lines=7,
            label="Agent persona",
            hint_text="말투, 태도, 설명 깊이, 작업 습관…",
            border_color=theme.BORDER_SUBTLE,
            cursor_color=theme.ACCENT,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=12),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            hint_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=11),
        )
        return _padded_column(
            [
                _label("Global identity"),
                self._user_profile_toggle,
                ft.Container(height=8),
                self._user_profile_field,
                ft.Container(height=14),
                _hint(
                    "모든 세션에 공통으로 실리는 사용자 정보야. 네 배경, 선호 답변 방식, "
                    "싫어하는 것 같은 고정 문맥을 넣으면 돼."
                ),
                ft.Container(height=20),
                _label("Global persona"),
                self._agent_persona_toggle,
                ft.Container(height=8),
                self._agent_persona_field,
                ft.Container(height=14),
                _hint(
                    "에이전트의 말투나 태도 같은 전역 페르소나야. 끄면 즉시 prompt에서 빠져."
                ),
            ]
        )

    # --------------------------------------------------------------- tab 4

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
            label="Model auto-compact threshold (tokens)",
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self._gemini_thinking_dropdown = ft.Dropdown(
            value=getattr(self.settings, "gemini_thinking_effort", "low"),
            options=[
                ft.dropdown.Option(key=level, text=level.capitalize())
                for level in GEMINI_THINKING_EFFORTS
            ],
            label="Gemini thinking effort",
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
        )
        summary_card = self._token_usage_summary_card()
        children: list[ft.Control] = [
            _label("Token budgets"),
            self._max_tokens_field,
            ft.Container(height=10),
            self._compact_field,
            ft.Container(height=10),
            self._gemini_thinking_dropdown,
        ]
        if summary_card is not None:
            children.extend(
                [
                    ft.Container(height=16),
                    _label("Current session usage"),
                    summary_card,
                ]
            )
        children.extend(
            [
                ft.Container(height=14),
                _hint(
                    "모델에게 보내는 컨텍스트만 줄여. 네가 보는 transcript는 그대로 두고, 0이면 자동 compact를 끈다. "
                    "Gemini thinking effort는 low/medium/high/max에 따라 0/5k/10k/20k budget으로 이어져."
                ),
            ]
        )
        return _padded_column(
            children
        )

    def _token_usage_summary_card(self) -> ft.Container | None:
        session = self._session
        if session is None:
            return None

        total_tokens = (
            int(getattr(session, "total_input_tokens", 0) or 0)
            + int(getattr(session, "total_output_tokens", 0) or 0)
            + int(getattr(session, "total_cache_creation_input_tokens", 0) or 0)
            + int(getattr(session, "total_cache_read_input_tokens", 0) or 0)
        )
        subagent_tokens = (
            int(getattr(session, "subagent_total_input_tokens", 0) or 0)
            + int(getattr(session, "subagent_total_output_tokens", 0) or 0)
            + int(getattr(session, "subagent_total_cache_creation_input_tokens", 0) or 0)
            + int(getattr(session, "subagent_total_cache_read_input_tokens", 0) or 0)
        )
        lines = [
            f"Total: {total_tokens:,}",
            (
                "Breakdown: "
                f"in {int(getattr(session, 'total_input_tokens', 0) or 0):,} · "
                f"out {int(getattr(session, 'total_output_tokens', 0) or 0):,}"
            ),
            (
                "Cache: "
                f"create {int(getattr(session, 'total_cache_creation_input_tokens', 0) or 0):,} · "
                f"read {int(getattr(session, 'total_cache_read_input_tokens', 0) or 0):,}"
            ),
            f"Sub-agents: {subagent_tokens:,}",
            f"Estimated cost: ${float(getattr(session, 'total_estimated_cost_usd', 0.0) or 0.0):.4f}",
        ]
        usage_by_model = normalize_usage_by_model(getattr(session, "usage_by_model", {}))
        if usage_by_model:
            lines.append("By model:")
        for model_name, entry in sorted(
            usage_by_model.items(),
            key=lambda item: float(item[1].get("cost_usd", 0.0) or 0.0),
            reverse=True,
        ):
            model_total = (
                int(entry.get("input_tokens", 0) or 0)
                + int(entry.get("output_tokens", 0) or 0)
                + int(entry.get("cache_creation_input_tokens", 0) or 0)
                + int(entry.get("cache_read_input_tokens", 0) or 0)
            )
            lines.append(
                f"{model_name}: {model_total:,} · ${float(entry.get('cost_usd', 0.0) or 0.0):.4f}"
            )
        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        line,
                        color=theme.TEXT_SECONDARY,
                        size=12,
                        font_family=theme.FONT_MONO,
                    )
                    for line in lines
                ],
                spacing=6,
                tight=True,
            ),
            bgcolor=theme.BG_DEEPEST,
            border=ft.border.all(1, theme.BORDER_SUBTLE),
            border_radius=theme.RADIUS_MD,
            padding=ft.padding.all(12),
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
            on_select=self._on_font_preset_change,
        )
        self._font_size_label = ft.Text(
            f"{self.settings.font_size}px",
            color=theme.TEXT_SECONDARY, size=12, width=36,
        )
        font_size_slider = ft.Slider(
            min=12, max=24, divisions=12,
            value=self.settings.font_size,
            label="{value}px",
            active_color=theme.ACCENT,
            inactive_color=theme.BORDER_SUBTLE,
            on_change=self._on_font_size_change,
            width=200,
        )

        self._appearance_preview = ft.Container()
        self._refresh_appearance_preview()

        return _padded_column(
            [
                _label("Color theme"),
                ft.Text(
                    "Select a palette. Preview updates instantly below.",
                    color=theme.TEXT_TERTIARY, size=11, italic=True,
                ),
                ft.Container(height=8),
                color_grid,
                ft.Container(height=16),
                _label("Font"),
                font_dropdown,
                ft.Container(height=12),
                _label("Font size"),
                ft.Row(
                    [
                        ft.Text("12", color=theme.TEXT_TERTIARY, size=11),
                        font_size_slider,
                        ft.Text("24", color=theme.TEXT_TERTIARY, size=11),
                        self._font_size_label,
                    ],
                    spacing=4,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=16),
                _label("Preview"),
                self._appearance_preview,
                ft.Container(height=8),
                ft.Text(
                    "Dark / light 둘 다 같이 보여줄게. 실제 앱 반영은 Save 때 돼.",
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
        self._refresh_appearance_preview()

    def _on_font_preset_change(self, e) -> None:
        self.settings.font_preset = e.control.value or self.settings.font_preset
        self._refresh_appearance_preview()

    def _on_font_size_change(self, e) -> None:
        self.settings.font_size = int(e.control.value)
        self._font_size_label.value = f"{self.settings.font_size}px"
        try:
            self._font_size_label.update()
        except Exception:
            pass
        self._refresh_appearance_preview()

    def _refresh_appearance_preview(self) -> None:
        from . import theme as theme_mod

        dark_tokens, light_tokens = theme_mod.COLOR_PRESETS.get(
            self.settings.color_preset,
            next(iter(theme_mod.COLOR_PRESETS.values())),
        )
        self._appearance_preview.content = ft.ResponsiveRow(
            [
                ft.Container(
                    col={"xs": 12, "md": 6},
                    content=self._appearance_preview_card("Dark", dark_tokens),
                ),
                ft.Container(
                    col={"xs": 12, "md": 6},
                    content=self._appearance_preview_card("Light", light_tokens),
                ),
            ],
            columns=12,
            spacing=10,
            run_spacing=10,
        )
        try:
            self._appearance_preview.update()
        except Exception:
            pass

    def _appearance_preview_card(self, title: str, tokens) -> ft.Container:
        from . import theme as theme_mod

        preset = theme_mod.FONT_PRESETS.get(
            self.settings.font_preset,
            theme_mod.FONT_PRESETS["System (Sans)"],
        )
        sans_font = preset["sans"]
        sans_fb = list(preset.get("sans_fallback", []))
        mono_font = preset["mono"]
        mono_fb = list(preset.get("mono_fallback", []))
        sz = self.settings.font_size

        # --- user bubble (right-aligned) ---
        user_bubble = ft.Container(
            content=ft.Text(
                "이건 내가 보낸 메시지야",
                color=tokens.TEXT_PRIMARY,
                size=sz,
                font_family=sans_font,
                font_family_fallback=sans_fb,
            ),
            bgcolor=tokens.BG_ELEVATED,
            padding=ft.padding.symmetric(horizontal=16, vertical=12),
            border_radius=theme.RADIUS_LG,
        )

        # --- assistant response ---
        assistant_text = ft.Text(
            "그렇구나. 뭐든 편하게 얘기해, 여기서 같이 정리하자.",
            color=tokens.TEXT_PRIMARY,
            size=sz,
            font_family=sans_font,
            font_family_fallback=sans_fb,
            height=1.55,
        )

        # --- tool call panel ---
        tool_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        "> bash  rg -n \"preview\" settings_dialog.py",
                        color=tokens.ACCENT,
                        size=sz - 3,
                        font_family=mono_font,
                        font_family_fallback=mono_fb,
                        weight=ft.FontWeight.W_600,
                    ),
                    ft.Text(
                        "exit_code: 0",
                        color=tokens.SUCCESS,
                        size=sz - 4,
                        font_family=mono_font,
                        font_family_fallback=mono_fb,
                    ),
                ],
                spacing=3,
                tight=True,
            ),
            border=ft.border.only(left=ft.BorderSide(1, tokens.BORDER_FAINT)),
            padding=ft.padding.only(left=12, top=2, bottom=2),
        )

        # --- code block ---
        code_block = ft.Container(
            content=ft.Text(
                "print(\"hello, world\")",
                color=tokens.TEXT_SECONDARY,
                size=sz - 3,
                font_family=mono_font,
                font_family_fallback=mono_fb,
            ),
            bgcolor=tokens.BG_DEEPEST,
            border=ft.border.all(1, tokens.BORDER_SUBTLE),
            border_radius=theme.RADIUS_MD,
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
        )

        # --- mode badge ---
        badge = ft.Container(
            content=ft.Text(
                title,
                color=tokens.TEXT_TERTIARY,
                size=9,
                font_family=mono_font,
                weight=ft.FontWeight.W_700,
            ),
            bgcolor=tokens.BG_ELEVATED,
            border_radius=theme.RADIUS_SM,
            padding=ft.padding.symmetric(horizontal=6, vertical=2),
        )

        return ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [ft.Container(expand=True), badge],
                    ),
                    ft.Container(height=6),
                    # user bubble right-aligned
                    ft.Row(
                        [ft.Container(expand=True), user_bubble],
                    ),
                    ft.Container(height=10),
                    # assistant response left-aligned
                    assistant_text,
                    ft.Container(height=8),
                    tool_panel,
                    ft.Container(height=8),
                    code_block,
                ],
                spacing=0,
                tight=True,
            ),
            bgcolor=tokens.BG_PAGE,
            border=ft.border.all(1, tokens.BORDER_FAINT),
            border_radius=theme.RADIUS_MD,
            padding=ft.padding.all(14),
        )

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
                self.settings.last_session_cwd = result
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
        style_defs = output_styles.all_styles(self._session.cwd if self._session else None)
        style_names = {style.name for style in style_defs}
        current_style = getattr(self.settings, "output_style", "default") or "default"
        if current_style not in style_names:
            current_style = "default"

        def _style_help_text(name: str | None) -> str:
            active_name = str(name or "default").strip().lower() or "default"
            style = next((item for item in style_defs if item.name == active_name), None)
            if style is None:
                return ""
            if style.description:
                return style.description
            if style.prompt:
                return style.prompt
            return "No extra output-style prompt. Uses the default response behavior."

        def _on_output_style_change(e) -> None:
            self._output_style_help.value = _style_help_text(self._output_style_dropdown.value)
            try:
                self._output_style_help.update()
            except Exception:
                pass

        self._output_style_dropdown = ft.Dropdown(
            value=current_style,
            options=[ft.dropdown.Option(key=style.name, text=style.label) for style in style_defs],
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            label="Output style",
            on_select=_on_output_style_change,
            expand=True,
        )
        self._output_style_help = ft.Text(
            _style_help_text(self._output_style_dropdown.value),
            color=theme.TEXT_TERTIARY,
            size=11,
            italic=True,
        )

        self._preset_dropdown = ft.Dropdown(
            value=self._active_preset_name,
            options=[ft.dropdown.Option(key=p.slug, text=p.name) for p in self._presets],
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            on_select=self._on_preset_change,
            expand=True,
        )
        self._default_preset_badge = ft.Container()
        self._set_default_btn = ft.OutlinedButton(
            content=ft.Text("Make default", color=theme.TEXT_PRIMARY, size=12, weight=ft.FontWeight.W_500),
            icon=ft.Icons.STAR_BORDER,
            on_click=self._on_make_default_preset,
        )
        self._refresh_default_preset_controls()

        # Prefix field
        initial_prefix = prompts.resolve_active_prefix(self._active_preset_name)
        self._prefix_field = ft.TextField(
            value=initial_prefix,
            multiline=False,
            label="Prefix (첫 줄 — 비우면 기본 'You are Claude Code...')",
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=12),
            label_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=12),
            hint_text="예: 나는 유리나, 주현이의 코딩 파트너.",
            hint_style=ft.TextStyle(color=theme.TEXT_TERTIARY, size=11),
            read_only=self._is_builtin_selected(),
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
                ft.Text("Response style", color=theme.TEXT_TERTIARY, size=12),
                self._output_style_dropdown,
                self._output_style_help,
                ft.Container(height=12),
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text("Preset to edit", color=theme.TEXT_TERTIARY, size=12),
                                self._preset_dropdown,
                            ],
                            spacing=6,
                            expand=True,
                            tight=True,
                        ),
                        ft.Container(width=12),
                        ft.Column(
                            [
                                ft.Text("App default", color=theme.TEXT_TERTIARY, size=12),
                                ft.Row(
                                    [self._default_preset_badge, self._set_default_btn],
                                    spacing=8,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            spacing=6,
                            tight=True,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                ft.Container(height=10),
                self._prefix_field,
                ft.Container(height=8),
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
        self._prefix_field.value = prompts.resolve_active_prefix(name)
        is_builtin = self._is_builtin_selected()
        self._prompt_editor.read_only = is_builtin
        self._prefix_field.read_only = is_builtin
        self._prompt_dirty = False
        self._name_field.value = ""
        self._prompt_feedback.value = ""
        self._refresh_default_preset_controls()
        try:
            self._prompt_editor.update()
            self._prefix_field.update()
            self._name_field.update()
            self._prompt_feedback.update()
        except Exception:
            pass

    def _on_editor_change(self, e) -> None:
        self._prompt_dirty = True

    def _refresh_default_preset_controls(self) -> None:
        selected_name = (self._active_preset_name or "").strip()
        default_name = self._default_preset_name or prompts.BUILTIN_NAME
        is_selected_default = bool(selected_name) and selected_name == default_name
        default_label = self._preset_label(default_name)

        badge_bg = theme.ACCENT if selected_name and is_selected_default else theme.BG_HOVER
        badge_fg = theme.TEXT_ON_ACCENT if selected_name and is_selected_default else theme.TEXT_SECONDARY
        badge_icon = ft.Icons.CHECK if selected_name and is_selected_default else ft.Icons.STAR

        self._default_preset_badge.content = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(badge_icon, size=12, color=badge_fg),
                    ft.Text(default_label, color=badge_fg, size=12, weight=ft.FontWeight.W_600),
                ],
                spacing=6,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.symmetric(horizontal=10, vertical=9),
            border_radius=theme.RADIUS_MD,
            bgcolor=badge_bg,
            border=ft.border.all(1, theme.BORDER_SUBTLE if badge_bg == theme.BG_HOVER else badge_bg),
        )

        if not selected_name:
            self._set_default_btn.content = ft.Text(
                "Save new preset first",
                color=theme.TEXT_TERTIARY,
                size=12,
                weight=ft.FontWeight.W_500,
            )
            self._set_default_btn.icon = ft.Icons.LOCK_OUTLINE
            self._set_default_btn.disabled = True
        elif is_selected_default:
            self._set_default_btn.content = ft.Text(
                "Using as default",
                color=theme.TEXT_TERTIARY,
                size=12,
                weight=ft.FontWeight.W_500,
            )
            self._set_default_btn.icon = ft.Icons.CHECK
            self._set_default_btn.disabled = True
        else:
            self._set_default_btn.content = ft.Text(
                "Make default",
                color=theme.TEXT_PRIMARY,
                size=12,
                weight=ft.FontWeight.W_500,
            )
            self._set_default_btn.icon = ft.Icons.STAR_BORDER
            self._set_default_btn.disabled = False

        for control in (self._default_preset_badge, self._set_default_btn):
            try:
                control.update()
            except Exception:
                pass

    def _on_make_default_preset(self, e) -> None:
        selected_name = (self._active_preset_name or "").strip()
        if not selected_name:
            return
        self._default_preset_name = selected_name
        self._prompt_feedback.value = (
            f"'{self._preset_label(selected_name)}' will be used as the app default when you save settings."
        )
        self._refresh_default_preset_controls()
        try:
            self._prompt_feedback.update()
        except Exception:
            pass

    def _on_new_blank(self, e) -> None:
        self._prompt_editor.value = ""
        self._prompt_editor.read_only = False
        self._active_preset_name = ""
        self._preset_dropdown.value = None
        self._name_field.value = ""
        self._prompt_feedback.value = "Start typing a new preset, then enter a name and click Save."
        self._refresh_default_preset_controls()
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
        base_name = self._preset_label(self._active_preset_name) or "copy"
        self._name_field.value = f"{base_name}-copy"
        self._active_preset_name = ""
        self._preset_dropdown.value = None
        self._prompt_feedback.value = "Edit freely and Save under a new name."
        self._refresh_default_preset_controls()
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
                name = self._preset_label(self._active_preset_name)
            else:
                self._prompt_feedback.value = "Enter a name to save as a new preset."
                try:
                    self._prompt_feedback.update()
                except Exception:
                    pass
                return
        prefix = (self._prefix_field.value or "").strip()
        try:
            preset = prompts.save_preset(name, text, prefix=prefix)
        except ValueError as exc:
            self._prompt_feedback.value = f"error: {exc}"
            try:
                self._prompt_feedback.update()
            except Exception:
                pass
            return
        # Refresh dropdown
        self._presets = prompts.list_presets()
        self._preset_dropdown.options = [ft.dropdown.Option(key=p.slug, text=p.name) for p in self._presets]
        self._preset_dropdown.value = preset.slug
        self._active_preset_name = preset.slug
        self._prompt_dirty = False
        self._name_field.value = ""
        self._prompt_feedback.value = f"Saved as '{preset.name}'."
        self._refresh_default_preset_controls()
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
        deleted_name = self._active_preset_name
        self._presets = prompts.list_presets()
        self._preset_dropdown.options = [ft.dropdown.Option(key=p.slug, text=p.name) for p in self._presets]
        self._preset_dropdown.value = prompts.BUILTIN_NAME
        self._active_preset_name = prompts.BUILTIN_NAME
        if self._default_preset_name == deleted_name:
            self._default_preset_name = prompts.BUILTIN_NAME
        self._prompt_editor.value = prompts.resolve_active(prompts.BUILTIN_NAME)
        self._prompt_editor.read_only = True
        self._prompt_feedback.value = "Deleted."
        self._refresh_default_preset_controls()
        try:
            self._preset_dropdown.update()
            self._prompt_editor.update()
            self._prompt_feedback.update()
        except Exception:
            pass

    # --------------------------------------------------------- commit

    def _commit_general_fields(self) -> None:
        self.settings.active_provider = self._provider_radio.value or "anthropic"
        self.settings.openai_model = self._openai_dropdown.value or self.settings.openai_model
        self.settings.anthropic_model = self._anth_dropdown.value or self.settings.anthropic_model
        self.settings.gemini_model = self._gem_dropdown.value or self.settings.gemini_model
        self.settings.gemini_thinking_effort = (
            self._gemini_thinking_dropdown.value
            or getattr(self.settings, "gemini_thinking_effort", "low")
        )
        self.settings.active_prompt = self._default_preset_name or prompts.BUILTIN_NAME
        self.settings.output_style = self._output_style_dropdown.value or "default"
        self.settings.user_profile_enabled = bool(self._user_profile_toggle.value)
        self.settings.user_profile_text = self._user_profile_field.value or ""
        self.settings.agent_persona_enabled = bool(self._agent_persona_toggle.value)
        self.settings.agent_persona_text = self._agent_persona_field.value or ""

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
                self._openai_key_field.value or "",
                self._anth_key_field.value or "",
                self._gem_key_field.value or "",
            )
        except Exception:
            pass

    def _persist_keys(self, openai: str, anth: str, gem: str) -> None:
        """Upsert provider API keys into the .env file.

        SAFETY: empty values are NEVER written. If the user leaves a field blank,
        the existing value in .env is preserved. This prevents accidental
        destruction of secrets when the dialog is saved without touching them.
        """
        openai = (openai or "").strip()
        anth = (anth or "").strip()
        gem = (gem or "").strip()
        if not openai and not anth and not gem:
            return  # nothing to do
        if not self._env_path.exists():
            self._env_path.parent.mkdir(parents=True, exist_ok=True)
            self._env_path.touch()
        lines = self._env_path.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        seen_openai = False
        seen_anth = False
        seen_gem = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("OPENAI_API_KEY="):
                if openai:
                    out.append(f"OPENAI_API_KEY={openai}")
                else:
                    out.append(line)
                seen_openai = True
            elif stripped.startswith("ANTHROPIC_API_KEY="):
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
        if not seen_openai and openai:
            out.append(f"OPENAI_API_KEY={openai}")
        if not seen_anth and anth:
            out.append(f"ANTHROPIC_API_KEY={anth}")
        if not seen_gem and gem:
            out.append(f"GEMINI_API_KEY={gem}")
        self._env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
        load_env_files()


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
