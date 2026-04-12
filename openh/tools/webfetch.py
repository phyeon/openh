"""WebFetch tool — fetch a URL and return extracted text content."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, ClassVar

from ..messages import Message, TextBlock, TextDelta, Usage
from .base import PermissionDecision, PermissionLevel, Tool, ToolContext

MAX_BYTES = 1_000_000
MAX_RESPONSE_CHARS = 60_000
SEMANTIC_EXTRACTION_HTML_LIMIT = 20_000
SEMANTIC_EXTRACTION_MAX_TOKENS = 2_000


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
        is_html = "html" in content_type or "<html" in content.lower()

        if is_html:
            text = _strip_html(content)
            if _is_edge_case_html(content, text):
                cached = _load_cached_extraction(url)
                if cached:
                    text = cached
                else:
                    extracted = await _semantic_extraction(content, ctx)
                    if extracted:
                        text = extracted
                        _save_cached_extraction(url, extracted)
        else:
            text = content.strip()

        if len(text) > MAX_RESPONSE_CHARS:
            text = text[:MAX_RESPONSE_CHARS] + f"\n…(truncated, +{len(text) - MAX_RESPONSE_CHARS} chars)"

        return f"# {url}\n\n{text}"


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _get_cache_dir() -> Path:
    return Path.home() / ".claurst" / "web_cache"


def _load_cached_extraction(url: str) -> str | None:
    cache_file = _get_cache_dir() / f"{_url_hash(url)}.txt"
    if not cache_file.exists():
        return None
    try:
        return cache_file.read_text(encoding="utf-8")
    except OSError:
        return None


def _save_cached_extraction(url: str, content: str) -> None:
    cache_dir = _get_cache_dir()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / f"{_url_hash(url)}.txt").write_text(content, encoding="utf-8")
    except OSError:
        return


def _is_edge_case_html(html: str, extracted_text: str) -> bool:
    word_count = len(extracted_text.split())
    if word_count < 100:
        return True

    lower = html.lower()
    has_semantic = "<article" in lower or "<main" in lower or "<body" in lower
    return not has_semantic


async def _semantic_extraction(html: str, ctx: ToolContext) -> str | None:
    html_excerpt = html
    if len(html_excerpt) > SEMANTIC_EXTRACTION_HTML_LIMIT:
        html_excerpt = f"{html_excerpt[:SEMANTIC_EXTRACTION_HTML_LIMIT]}..."

    system = (
        "You are a content extraction expert. Given HTML, extract and return only "
        "the main text content. Return just plain text, no markdown or formatting."
    )
    user_message = (
        "Extract the main content from this HTML and return only the text:\n\n"
        f"{html_excerpt}"
    )

    provider = ctx.session.provider
    try:
        if ctx.session.config.anthropic_api_key:
            from ..providers.anthropic import AnthropicProvider

            provider = AnthropicProvider(
                api_key=ctx.session.config.anthropic_api_key,
                model="claude-haiku-4-5",
            )
    except Exception:
        provider = ctx.session.provider

    messages = [Message(role="user", content=[TextBlock(text=user_message)])]
    chunks: list[str] = []
    usage: Usage | None = None
    try:
        async for event in provider.stream(
            messages,
            system,
            [],
            max_tokens=SEMANTIC_EXTRACTION_MAX_TOKENS,
        ):
            if isinstance(event, TextDelta):
                chunks.append(event.text)
            elif isinstance(event, Usage):
                usage = event
    except Exception:
        return None

    extracted = "".join(chunks).strip()
    if not extracted:
        return None

    if usage is not None:
        ctx.session.add_tokens(
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_creation_input_tokens,
            usage.cache_read_input_tokens,
            model=getattr(provider, "model", None),
            update_last_input=False,
        )
    return extracted


def _strip_html(html: str) -> str:
    result: list[str] = []
    in_tag = False
    in_script = False
    in_style = False
    lower = html.lower()
    chars = list(html)
    lower_chars = list(lower)
    length = len(chars)
    index = 0

    while index < length:
        if not in_tag and chars[index] == "<":
            in_tag = True
            rest = "".join(lower_chars[index:index + 20])
            if rest.startswith("<script"):
                in_script = True
            elif rest.startswith("</script"):
                in_script = False
            elif rest.startswith("<style"):
                in_style = True
            elif rest.startswith("</style"):
                in_style = False

            for tag in (
                "<br",
                "<p ",
                "<p>",
                "</p>",
                "<div",
                "</div>",
                "<h1",
                "<h2",
                "<h3",
                "<h4",
                "<h5",
                "<h6",
                "</h1",
                "</h2",
                "</h3",
                "</h4",
                "</h5",
                "</h6",
                "<li",
                "</li",
                "<tr",
                "</tr",
                "<hr",
            ):
                if rest.startswith(tag):
                    result.append("\n")
                    break
            index += 1
            continue

        if in_tag:
            if chars[index] == ">":
                in_tag = False
            index += 1
            continue

        if in_script or in_style:
            index += 1
            continue

        if chars[index] == "&":
            rest = "".join(chars[index:index + 10])
            if rest.startswith("&amp;"):
                result.append("&")
                index += 5
                continue
            if rest.startswith("&lt;"):
                result.append("<")
                index += 4
                continue
            if rest.startswith("&gt;"):
                result.append(">")
                index += 4
                continue
            if rest.startswith("&quot;"):
                result.append('"')
                index += 6
                continue
            if rest.startswith("&#39;") or rest.startswith("&apos;"):
                result.append("'")
                index += 5 if rest.startswith("&#39;") else 6
                continue
            if rest.startswith("&nbsp;"):
                result.append(" ")
                index += 6
                continue

        result.append(chars[index])
        index += 1

    collapsed: list[str] = []
    blank_count = 0
    for line in "".join(result).splitlines():
        trimmed = line.strip()
        if not trimmed:
            blank_count += 1
            if blank_count <= 2:
                collapsed.append("")
            continue
        blank_count = 0
        collapsed.append(trimmed)
    return "\n".join(collapsed).strip()
