"""WebSearch tool — DuckDuckGo HTML endpoint (no API key required)."""
from __future__ import annotations

import re
from typing import Any, ClassVar

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext

MAX_RESULTS = 10


class WebSearchTool(Tool):
    name: ClassVar[str] = "WebSearch"
    permission_level = PermissionLevel.READ_ONLY
    description: ClassVar[str] = (
        "Allows searching the web and using the results to inform responses. "
        "Provides up-to-date information for current events and recent data. "
        "Use this tool for accessing information beyond the knowledge cutoff. "
        "Use WebFetch to then retrieve the full content of any interesting result."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
        },
        "required": ["query"],
    }
    is_read_only: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        query = (input.get("query") or "").strip()
        if not query:
            return "error: query is required"

        try:
            import httpx
        except ImportError:
            return "error: httpx is required for WebSearch"

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                resp = await client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (openh)"},
                )
        except Exception as exc:  # noqa: BLE001
            return f"error: search failed: {exc}"

        if resp.status_code != 200:
            return f"error: HTTP {resp.status_code}"

        results = _parse_ddg_html(resp.text)
        if not results:
            return f"no results for: {query}"

        lines = [f"# Search: {query}", ""]
        for i, (title, url, snippet) in enumerate(results[:MAX_RESULTS], start=1):
            lines.append(f"{i}. **{title}**")
            lines.append(f"   {url}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")
        return "\n".join(lines)


_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_TAG = re.compile(r"<[^>]+>")


def _parse_ddg_html(html: str) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    for match in _RESULT_RE.finditer(html):
        raw_url = match.group(1)
        # DuckDuckGo wraps URLs — strip the wrapper if needed
        import urllib.parse
        if "uddg=" in raw_url:
            qs = urllib.parse.urlparse(raw_url).query
            params = urllib.parse.parse_qs(qs)
            if "uddg" in params:
                raw_url = params["uddg"][0]
        title = _TAG.sub("", match.group(2)).strip()
        snippet = _TAG.sub("", match.group(3)).strip()
        results.append((title, raw_url, snippet))
    return results
