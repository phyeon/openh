"""Usage dashboard dialog — aggregated token/cost view across sessions."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta

import flet as ft

from . import theme
from ..cc_compat import UsageAggregate, aggregate_usage


_DATE_RANGES = {
    "Today": lambda: (
        datetime.now().replace(hour=0, minute=0, second=0).timestamp(),
        0.0,
    ),
    "Last 7 days": lambda: (time.time() - 7 * 86400, 0.0),
    "This month": lambda: (
        datetime.now().replace(day=1, hour=0, minute=0, second=0).timestamp(),
        0.0,
    ),
    "Last 30 days": lambda: (time.time() - 30 * 86400, 0.0),
    "All time": lambda: (0.0, 0.0),
}


def _fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _fmt_cost(usd: float) -> str:
    if usd >= 1.0:
        return f"${usd:.2f}"
    return f"${usd:.4f}"


class UsageDialog:
    def __init__(self, page: ft.Page) -> None:
        self._page = page
        self._range_key = "This month"
        self._body = ft.Column(spacing=8, expand=True, scroll=ft.ScrollMode.AUTO)
        self._loading = ft.ProgressRing(width=24, height=24, color=theme.ACCENT)
        self._dropdown = ft.Dropdown(
            value=self._range_key,
            options=[ft.dropdown.Option(k) for k in _DATE_RANGES],
            border_color=theme.BORDER_SUBTLE,
            text_style=ft.TextStyle(color=theme.TEXT_PRIMARY, size=13),
            width=180,
            on_change=self._on_range_change,
        )

    def open(self) -> None:
        self._body.controls = [
            ft.Container(
                content=self._loading,
                alignment=ft.alignment.center,
                padding=40,
            )
        ]
        dialog = ft.AlertDialog(
            modal=False,
            bgcolor=theme.BG_ELEVATED,
            title=ft.Row(
                [
                    ft.Text("Usage Summary", color=theme.TEXT_PRIMARY, size=16, weight=ft.FontWeight.W_600),
                    ft.Container(expand=True),
                    self._dropdown,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            content=ft.Container(
                content=self._body,
                width=520,
                height=480,
            ),
            actions=[
                ft.TextButton("Close", on_click=lambda _: self._close()),
            ],
        )
        self._page.show_dialog(dialog)
        self._page.run_task(self._load_async)

    def _close(self) -> None:
        try:
            self._page.pop_dialog()
        except Exception:
            pass

    def _on_range_change(self, e) -> None:
        self._range_key = e.control.value or "This month"
        self._body.controls = [
            ft.Container(
                content=self._loading,
                alignment=ft.alignment.center,
                padding=40,
            )
        ]
        try:
            self._body.update()
        except Exception:
            pass
        self._page.run_task(self._load_async)

    async def _load_async(self) -> None:
        since, until = _DATE_RANGES[self._range_key]()
        agg = await asyncio.to_thread(aggregate_usage, since, until)
        self._render(agg)

    def _render(self, agg: UsageAggregate) -> None:
        controls: list[ft.Control] = []

        if agg.session_count == 0:
            controls.append(
                ft.Container(
                    content=ft.Text(
                        "No usage data for this period.",
                        color=theme.TEXT_TERTIARY,
                        size=13,
                        italic=True,
                    ),
                    padding=20,
                    alignment=ft.alignment.center,
                )
            )
            self._body.controls = controls
            try:
                self._body.update()
            except Exception:
                pass
            return

        total_tokens = agg.total_input_tokens + agg.total_output_tokens
        # Summary section
        summary_rows = [
            ("Total cost", _fmt_cost(agg.total_cost_usd)),
            ("Sessions", str(agg.session_count)),
            ("Total tokens", _fmt_tokens(total_tokens)),
            ("  Input", _fmt_tokens(agg.total_input_tokens)),
            ("  Output", _fmt_tokens(agg.total_output_tokens)),
        ]
        if agg.total_cache_creation_input_tokens or agg.total_cache_read_input_tokens:
            summary_rows.append(
                ("  Cache write", _fmt_tokens(agg.total_cache_creation_input_tokens))
            )
            summary_rows.append(
                ("  Cache read", _fmt_tokens(agg.total_cache_read_input_tokens))
            )

        summary_col = ft.Column(spacing=2)
        for label, value in summary_rows:
            summary_col.controls.append(
                ft.Row(
                    [
                        ft.Text(label, color=theme.TEXT_SECONDARY, size=12, width=140),
                        ft.Text(value, color=theme.TEXT_PRIMARY, size=12, weight=ft.FontWeight.W_600),
                    ],
                    spacing=8,
                )
            )
        controls.append(
            ft.Container(
                content=summary_col,
                bgcolor=theme.BG_PAGE,
                border_radius=8,
                padding=14,
            )
        )

        # By model table
        if agg.usage_by_model:
            controls.append(ft.Container(height=8))
            controls.append(
                ft.Text("By model", color=theme.TEXT_TERTIARY, size=12, weight=ft.FontWeight.W_600)
            )
            model_rows: list[ft.DataRow] = []
            sorted_models = sorted(
                agg.usage_by_model.items(),
                key=lambda x: x[1].get("cost_usd", 0),
                reverse=True,
            )
            for model_name, mdata in sorted_models:
                mtokens = mdata.get("input_tokens", 0) + mdata.get("output_tokens", 0)
                mcost = mdata.get("cost_usd", 0.0)
                reqs = mdata.get("requests", 0)
                model_rows.append(
                    ft.DataRow(cells=[
                        ft.DataCell(ft.Text(model_name, size=11, color=theme.TEXT_PRIMARY)),
                        ft.DataCell(ft.Text(_fmt_tokens(mtokens), size=11, color=theme.TEXT_SECONDARY)),
                        ft.DataCell(ft.Text(str(reqs), size=11, color=theme.TEXT_SECONDARY)),
                        ft.DataCell(ft.Text(_fmt_cost(mcost), size=11, color=theme.TEXT_PRIMARY)),
                    ])
                )
            controls.append(
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Model", size=11, color=theme.TEXT_TERTIARY)),
                        ft.DataColumn(ft.Text("Tokens", size=11, color=theme.TEXT_TERTIARY)),
                        ft.DataColumn(ft.Text("Reqs", size=11, color=theme.TEXT_TERTIARY)),
                        ft.DataColumn(ft.Text("Cost", size=11, color=theme.TEXT_TERTIARY)),
                    ],
                    rows=model_rows,
                    border=ft.border.all(1, theme.BORDER_SUBTLE),
                    border_radius=6,
                    horizontal_lines=ft.border.BorderSide(1, theme.BORDER_SUBTLE),
                    column_spacing=16,
                    data_row_min_height=32,
                    heading_row_height=32,
                )
            )

        # By day table
        if agg.cost_by_date:
            controls.append(ft.Container(height=8))
            controls.append(
                ft.Text("By day", color=theme.TEXT_TERTIARY, size=12, weight=ft.FontWeight.W_600)
            )
            day_rows: list[ft.DataRow] = []
            for day, cost in sorted(agg.cost_by_date.items(), reverse=True)[:14]:
                day_rows.append(
                    ft.DataRow(cells=[
                        ft.DataCell(ft.Text(day, size=11, color=theme.TEXT_PRIMARY)),
                        ft.DataCell(ft.Text(_fmt_cost(cost), size=11, color=theme.TEXT_PRIMARY)),
                    ])
                )
            controls.append(
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Date", size=11, color=theme.TEXT_TERTIARY)),
                        ft.DataColumn(ft.Text("Cost", size=11, color=theme.TEXT_TERTIARY)),
                    ],
                    rows=day_rows,
                    border=ft.border.all(1, theme.BORDER_SUBTLE),
                    border_radius=6,
                    horizontal_lines=ft.border.BorderSide(1, theme.BORDER_SUBTLE),
                    column_spacing=16,
                    data_row_min_height=32,
                    heading_row_height=32,
                )
            )

        self._body.controls = controls
        try:
            self._body.update()
        except Exception:
            pass
