"""WebSearch tool — Brave Search API with DuckDuckGo fallback."""
from __future__ import annotations

import os
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
            "num_results": {
                "type": "number",
                "description": "Number of results to return (default: 5, max: 10).",
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
            num_results = int(input.get("num_results") or 5)
        except (TypeError, ValueError):
            num_results = 5
        num_results = max(1, min(MAX_RESULTS, num_results))

        api_key = (os.environ.get("BRAVE_SEARCH_API_KEY") or "").strip()
        if api_key:
            return await _search_brave(query, num_results, api_key)
        return await _search_duckduckgo(query, num_results)


async def _search_brave(query: str, num_results: int, api_key: str) -> str:
    try:
        import httpx
    except ImportError:
        return "error: httpx is required for WebSearch"

    url = (
        "https://api.search.brave.com/res/v1/web/search?"
        f"q={_urlencoding_simple(query)}&count={num_results}"
    )
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            resp = await client.get(
                url,
                headers={
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "User-Agent": "OpenH/1.0",
                    "X-Subscription-Token": api_key,
                },
            )
    except Exception as exc:  # noqa: BLE001
        return f"error: Search request failed: {exc}"

    if resp.status_code >= 400:
        return f"error: Brave Search API returned status {resp.status_code}"

    try:
        data = resp.json()
    except ValueError as exc:
        return f"error: Failed to parse response: {exc}"
    return _format_brave_results(data, num_results)


def _format_brave_results(data: dict[str, Any], max_results: int) -> str:
    output: list[str] = []
    items = (
        data.get("web", {}).get("results", [])
        if isinstance(data, dict)
        else []
    )
    for index, item in enumerate(items[:max_results], start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "(No title)")
        url = str(item.get("url") or "")
        snippet = str(item.get("description") or "")
        output.append(f"{index}. **{title}**")
        output.append(f"   URL: {url}")
        output.append(f"   {snippet}")
        output.append("")
    return "\n".join(output).strip() or "No results found."


async def _search_duckduckgo(query: str, num_results: int) -> str:
    try:
        import httpx
    except ImportError:
        return "error: httpx is required for WebSearch"

    url = (
        "https://api.duckduckgo.com/?"
        f"q={_urlencoding_simple(query)}&format=json&no_html=1&skip_disambig=1"
    )
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Claurst/1.0"},
            )
    except Exception as exc:  # noqa: BLE001
        return f"error: Search request failed: {exc}"

    if resp.status_code >= 400:
        return f"error: DuckDuckGo API returned status {resp.status_code}"

    try:
        data = resp.json()
    except ValueError as exc:
        return f"error: Failed to parse response: {exc}"
    return _format_ddg_results(data, num_results)


def _format_ddg_results(data: dict[str, Any], max_results: int) -> str:
    output: list[str] = []
    count = 0

    abstract_text = str(data.get("Abstract") or "")
    if abstract_text:
        source = str(data.get("AbstractSource") or "")
        url = str(data.get("AbstractURL") or "")
        output.append(f"**{source}**")
        output.append(abstract_text)
        output.append(f"URL: {url}")
        output.append("")
        count += 1

    topics = data.get("RelatedTopics")
    if isinstance(topics, list):
        remaining = max(0, max_results - count)
        for topic in topics[:remaining]:
            if not isinstance(topic, dict):
                continue
            text = str(topic.get("Text") or "")
            if not text:
                continue
            url = str(topic.get("FirstURL") or "")
            output.append(f"- {text}")
            output.append(f"  {url}")
            output.append("")

    if output:
        return "\n".join(output).strip()

    query_name = str(data.get("QuerySearchQuery") or "your query")
    return (
        f"No instant answer found for '{query_name}'. Try using the Brave Search API "
        "by setting the BRAVE_SEARCH_API_KEY environment variable for full web search."
    )


def _urlencoding_simple(value: str) -> str:
    encoded: list[str] = []
    for ch in value:
        if ch.isalnum() or ch in "-_.~":
            encoded.append(ch)
        elif ch == " ":
            encoded.append("+")
        else:
            for byte in ch.encode("utf-8"):
                encoded.append(f"%{byte:02X}")
    return "".join(encoded)
