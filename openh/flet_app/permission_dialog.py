"""Permission dialog as a Flet AlertDialog."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import flet as ft

from . import theme


class PermissionDialog:
    """A dialog that asks the user to allow / always-allow / deny a tool call.

    Returns one of: 'allow', 'always', 'deny'.
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

        def make_handler(decision: str):
            def _h(e):
                self._resolve(decision)
            return _h

        self._dialog = ft.AlertDialog(
            modal=True,
            bgcolor=theme.BG_PANEL,
            title=ft.Row(
                [
                    ft.Icon(ft.Icons.SHIELD_OUTLINED, color=theme.ACCENT, size=20),
                    ft.Text(
                        f"Allow {tool_name}?",
                        color=theme.TEXT_PRIMARY,
                        weight=ft.FontWeight.W_700,
                        size=16,
                    ),
                ],
                spacing=8,
                tight=True,
            ),
            content=ft.Container(
                width=560,
                content=ft.Column(
                    [
                        ft.Text(
                            description,
                            color=theme.TEXT_SECONDARY,
                            size=12,
                        ),
                        ft.Container(
                            content=ft.Text(
                                body,
                                font_family=theme.FONT_MONO,
                                size=11,
                                color=theme.TEXT_PRIMARY,
                                selectable=True,
                            ),
                            bgcolor=theme.BG_DEEPEST,
                            border=ft.border.all(1, theme.BORDER_SUBTLE),
                            border_radius=theme.RADIUS_SM,
                            padding=10,
                        ),
                    ],
                    spacing=10,
                    tight=True,
                ),
            ),
            actions=[
                ft.TextButton(
                    content=ft.Text("Deny", color=theme.TEXT_SECONDARY, size=13),
                    on_click=make_handler("deny"),
                ),
                ft.TextButton(
                    content=ft.Text("Allow always", color=theme.ACCENT, size=13),
                    on_click=make_handler("always"),
                ),
                ft.FilledButton(
                    content=ft.Text(
                        "Allow",
                        color=theme.TEXT_ON_ACCENT,
                        size=13,
                        weight=ft.FontWeight.W_600,
                    ),
                    on_click=make_handler("allow"),
                    style=ft.ButtonStyle(
                        bgcolor=theme.ACCENT,
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
