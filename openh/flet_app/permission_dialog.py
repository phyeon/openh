"""Permission dialog as a Flet AlertDialog."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import flet as ft

from . import theme


def _dialog_meta(tool_name: str, input_dict: dict[str, Any]) -> tuple[str, str, str]:
    name = str(tool_name or "")
    if name == "Bash":
        return "Allow Bash Command?", ft.Icons.TERMINAL, theme.WARN
    if name in {"Read", "Glob", "Grep"}:
        return "Allow File Read?", ft.Icons.DESCRIPTION_OUTLINED, theme.SUCCESS
    if name in {"Write", "Edit", "NotebookEdit"}:
        return "Allow File Write?", ft.Icons.EDIT_OUTLINED, theme.WARN
    if name == "WebFetch":
        return "Allow Web Fetch?", ft.Icons.LANGUAGE, theme.ACCENT
    if name == "WebSearch":
        return "Allow Web Search?", ft.Icons.SEARCH, theme.ACCENT
    if name == "AskUserQuestion":
        return "Allow Agent Question?", ft.Icons.HELP_OUTLINE, theme.ACCENT
    return f"Allow {name}?", ft.Icons.SHIELD_OUTLINED, theme.ACCENT


def _preview_lines(tool_name: str, input_dict: dict[str, Any]) -> tuple[str, str] | None:
    if tool_name == "Bash":
        command = str(input_dict.get("command") or "").strip()
        if command:
            return "Command", f"$ {command}"
    if tool_name in {"Read", "Write", "Edit", "NotebookEdit"}:
        path = str(
            input_dict.get("file_path")
            or input_dict.get("path")
            or ""
        ).strip()
        if path:
            return "File", path
    if tool_name in {"Glob", "Grep"}:
        pattern = str(input_dict.get("pattern") or input_dict.get("query") or "").strip()
        path = str(input_dict.get("path") or input_dict.get("cwd") or "").strip()
        preview = pattern or path
        if preview:
            return "Search", preview
    if tool_name == "WebFetch":
        url = str(input_dict.get("url") or "").strip()
        if url:
            return "URL", url
    if tool_name == "WebSearch":
        query = str(input_dict.get("query") or "").strip()
        if query:
            return "Query", query
    if tool_name == "AskUserQuestion":
        question = str(input_dict.get("question") or "").strip()
        if question:
            return "Question", question
    return None


class PermissionDialog:
    """A dialog that asks the user to allow / always-allow / deny a tool call.

    Returns one of: 'allow', 'always', 'deny', 'deny_always'.
    """

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self._future: asyncio.Future[str] | None = None
        self._dialog: ft.AlertDialog | None = None

    async def ask(self, tool_name: str, input_dict: dict[str, Any]) -> str:
        loop = asyncio.get_running_loop()
        self._future = loop.create_future()

        try:
            body = json.dumps(input_dict, indent=2, ensure_ascii=False)
        except Exception:
            body = str(input_dict)
        if len(body) > 1500:
            body = body[:1500] + "\n…(truncated)"

        description = theme.TOOL_DESCRIPTIONS.get(tool_name, "Run a tool")
        title_text, title_icon, accent = _dialog_meta(tool_name, input_dict)
        preview = _preview_lines(tool_name, input_dict)

        def make_handler(decision: str):
            def _h(e):
                self._resolve(decision)
            return _h

        self._dialog = ft.AlertDialog(
            modal=True,
            bgcolor=theme.BG_ELEVATED,
            content_padding=ft.padding.symmetric(horizontal=24, vertical=20),
            title=ft.Row(
                [
                    ft.Icon(title_icon, color=accent, size=20),
                    ft.Text(
                        title_text,
                        color=theme.TEXT_PRIMARY,
                        weight=ft.FontWeight.W_700,
                        size=16,
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            content=ft.Column(
                [
                    ft.Text(
                        description,
                        color=theme.TEXT_SECONDARY,
                        size=12,
                    ),
                    *(
                        [
                            ft.Container(
                                content=ft.Column(
                                    [
                                        ft.Text(
                                            preview[0],
                                            color=theme.TEXT_TERTIARY,
                                            size=11,
                                            font_family=theme.FONT_MONO,
                                        ),
                                        ft.Text(
                                            preview[1],
                                            font_family=theme.FONT_MONO,
                                            size=12,
                                            color=theme.TEXT_PRIMARY,
                                            selectable=True,
                                        ),
                                    ],
                                    spacing=6,
                                    tight=True,
                                ),
                                bgcolor=theme.BG_DEEPEST,
                                border=ft.border.all(1, theme.BORDER_SUBTLE),
                                border_radius=theme.RADIUS_SM,
                                padding=14,
                                width=520,
                            )
                        ]
                        if preview is not None
                        else []
                    ),
                    ft.Container(
                        content=ft.Text(
                            body,
                            font_family=theme.FONT_MONO,
                            size=11,
                            color=theme.TEXT_SECONDARY,
                            selectable=True,
                        ),
                        bgcolor=theme.BG_PAGE,
                        border=ft.border.all(1, theme.BORDER_FAINT),
                        border_radius=theme.RADIUS_SM,
                        padding=12,
                        width=520,
                    ),
                ],
                spacing=10,
                tight=True,
                width=520,
            ),
            actions=[
                ft.TextButton(
                    content=ft.Text("Deny", color=theme.TEXT_SECONDARY, size=13),
                    on_click=make_handler("deny"),
                ),
                ft.TextButton(
                    content=ft.Text("Always deny", color=theme.WARN, size=13),
                    on_click=make_handler("deny_always"),
                ),
                ft.TextButton(
                    content=ft.Text("Allow always", color=theme.ACCENT, size=13),
                    on_click=make_handler("always"),
                ),
                ft.FilledButton(
                    content=ft.Text(
                        "Allow once",
                        color=theme.TEXT_ON_ACCENT,
                        size=13,
                        weight=ft.FontWeight.W_600,
                    ),
                    on_click=make_handler("allow"),
                    style=ft.ButtonStyle(
                        bgcolor=accent,
                        color=theme.TEXT_ON_ACCENT,
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        self.page.show_dialog(self._dialog)
        try:
            return await self._future
        finally:
            if self._dialog is not None:
                try:
                    self.page.pop_dialog()
                except Exception:
                    pass
                self._dialog = None

    def _resolve(self, decision: str) -> None:
        if self._future and not self._future.done():
            self._future.set_result(decision)
