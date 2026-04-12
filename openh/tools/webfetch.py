"""WebFetch tool — fetch a URL and return text content (HTML stripped)."""
from __future__ import annotations

import asyncio
import re
from typing import Any, ClassVar

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext

MAX_BYTES = 1_000_000
MAX_RESPONSE_CHARS = 60_000


class WebFetchTool(Tool):
    name: ClassVar[str] = "WebFetch"
    permission_level = PermissionLevel.READ_ONLY
    description: ClassVar[str] = (
        "Fetches content from a specified URL. The URL must be fully-formed and valid. "
        "Fetches the URL content, converts HTML to markdown. "
        "Results may be summarized if the content is very large. "
        "Use this tool when you need to retrieve and analyze web content."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The fully-qualified URL to fetch.",
            },
            "prompt": {
                "type": "string",
                "description": "(Optional) What to look for on the page — for your own reference.",
            },
        },
        "required": ["url"],
    }
    is_read_only: ClassVar[bool] = True

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="allow")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        url = input.get("url", "").strip()
        if not url:
            return "error: url is required"
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        try:
            import httpx
        except ImportError:
            return "error: httpx is required for WebFetch"

        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (openh)"},
                )
        except Exception as exc:  # noqa: BLE001
            return f"error: fetch failed: {exc}"

        if resp.status_code >= 400:
            return f"error: HTTP {resp.status_code}"

        content = resp.text[:MAX_BYTES]
        content_type = resp.headers.get("content-type", "").lower()

        if "html" in content_type:
            text = _html_to_text(content)
        else:
            text = content

        if len(text) > MAX_RESPONSE_CHARS:
            text = text[:MAX_RESPONSE_CHARS] + f"\n…(truncated, +{len(text) - MAX_RESPONSE_CHARS} chars)"

        return f"# {url}\n\n{text}"


_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\n\s*\n\s*\n+")


def _html_to_text(html: str) -> str:
    html = _SCRIPT_STYLE.sub("", html)
    text = _TAG.sub("", html)
    # Unescape basic entities
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    text = _WS.sub("\n\n", text)
    return text.strip()
