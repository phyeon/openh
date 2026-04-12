"""Conversation auto-compact with summary-first compaction."""
from __future__ import annotations

import json

from .messages import (
    DocumentBlock,
    ImageBlock,
    Message,
    MessageStop,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
)

KEEP_RECENT_MESSAGES = 10
AUTOCOMPACT_TRIGGER_FRACTION = 0.90
COMPACT_SUMMARY_SYSTEM = (
    "You create continuation-grade coding conversation summaries. "
    "Preserve user intent, constraints, files, tool outcomes, errors, "
    "decisions, and what should happen next. Respond with plain text only."
)
COMPACT_SUMMARY_PROMPT = """CRITICAL: Respond with TEXT ONLY. Do not call any tools.

Summarize the conversation below so another coding agent can continue the work
without losing context.

Include:
1. The user's requests, constraints, and feedback
2. Important technical details, decisions, and architecture
3. Files read, edited, or created, and why they mattered
4. Tool calls and the important outcomes
5. Errors, debugging, and fixes attempted
6. Current status and the next concrete step

Wrap any scratch work in <analysis> tags and the final handoff in <summary> tags.
"""


def estimate_tokens(messages: list[Message]) -> int:
    """Rough char/4 estimate of total tokens."""
    total = 0
    for m in messages:
        for b in m.content:
            if isinstance(b, TextBlock):
                total += len(b.text)
            else:
                total += len(str(b.to_dict() if hasattr(b, "to_dict") else b))
    return total // 4


def context_window_for_model(model: str) -> int | None:
    name = (model or "").lower()
    if "claude" in name:
        return 200_000
    return None


def should_compact(
    messages: list[Message],
    threshold_tokens: int | None = None,
    *,
    model: str = "",
    usage_tokens: int = 0,
) -> bool:
    from .config import AUTO_COMPACT_THRESHOLD, MAX_CONVERSATION_MESSAGES

    if threshold_tokens is None:
        window = context_window_for_model(model)
        threshold_tokens = (
            int(window * AUTOCOMPACT_TRIGGER_FRACTION) if window else AUTO_COMPACT_THRESHOLD
        )
    if int(threshold_tokens or 0) <= 0:
        return False
    if len(messages) > MAX_CONVERSATION_MESSAGES:
        return True
    estimated = estimate_tokens(messages)
    return max(estimated, int(usage_tokens or 0)) >= threshold_tokens


async def compact_messages(
    messages: list[Message],
    provider: object = None,
    keep_recent: int = KEEP_RECENT_MESSAGES,
) -> list[Message]:
    """Summarize the older head of the conversation and keep the recent tail."""
    if len(messages) <= keep_recent:
        return messages

    split_at = len(messages) - keep_recent
    if split_at <= 0:
        return messages

    if provider is None or not hasattr(provider, "stream"):
        return _fallback_compaction(messages, keep_recent)

    try:
        return await _summarise_head(messages, split_at, provider)
    except Exception:
        return _fallback_compaction(messages, keep_recent)


async def _summarise_head(
    messages: list[Message],
    split_at: int,
    provider: object,
) -> list[Message]:
    head = messages[:split_at]
    tail = messages[split_at:]

    transcript = _messages_to_transcript(head)
    original_count = len(head)
    original_tokens = estimate_tokens(head)
    prompt = (
        COMPACT_SUMMARY_PROMPT
        + "\n\n"
        + f"<conversation_to_summarize original_messages=\"{original_count}\" "
        + f"estimated_tokens=\"{original_tokens}\">\n{transcript}\n"
        + "</conversation_to_summarize>"
    )

    stream = provider.stream(
        messages=[Message(role="user", content=[TextBlock(text=prompt)])],
        system=COMPACT_SUMMARY_SYSTEM,
        tools=[],
    )

    chunks: list[str] = []
    async for event in stream:
        if isinstance(event, TextDelta):
            chunks.append(event.text)
        elif isinstance(event, MessageStop):
            break

    raw_summary = "".join(chunks).strip()
    if not raw_summary:
        raise RuntimeError("empty compact summary")

    formatted = format_compact_summary(raw_summary)
    compact_notice = Message(
        role="user",
        content=[
            TextBlock(
                text=(
                    "This session is continuing from an earlier conversation that was "
                    "compacted to save context.\n\n"
                    f"Earlier segment: {original_count} messages, about {original_tokens} tokens.\n\n"
                    f"{formatted}"
                )
            )
        ],
    )
    return [compact_notice] + tail


def format_compact_summary(raw: str) -> str:
    text = raw

    if "<analysis>" in text and "</analysis>" in text:
        start = text.find("<analysis>")
        end = text.find("</analysis>") + len("</analysis>")
        text = (text[:start] + text[end:]).strip()

    if "<summary>" in text and "</summary>" in text:
        start = text.find("<summary>") + len("<summary>")
        end = text.find("</summary>")
        text = "Summary:\n" + text[start:end].strip()

    lines = [line.rstrip() for line in text.splitlines()]
    compacted: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if not blank:
                compacted.append("")
            blank = True
            continue
        compacted.append(line)
        blank = False
    return "\n".join(compacted).strip()


def _messages_to_transcript(messages: list[Message]) -> str:
    parts: list[str] = []

    for msg in messages:
        role = "Human" if msg.role == "user" else "Assistant"
        for block in msg.content:
            if isinstance(block, TextBlock):
                if block.text.strip():
                    parts.append(f"{role}: {block.text.strip()}")
            elif isinstance(block, ToolUseBlock):
                payload = json.dumps(block.input or {}, ensure_ascii=False, indent=2)
                parts.append(
                    f"[Tool Call: {block.name} (id={block.id})]\nInput:\n{payload}"
                )
            elif isinstance(block, ToolResultBlock):
                error_tag = " [ERROR]" if block.is_error else ""
                parts.append(
                    f"[Tool Result (id={block.tool_use_id}){error_tag}]\n{block.content}"
                )
            elif isinstance(block, ImageBlock):
                parts.append(f"{role}: [image attachment omitted for compaction]")
            elif isinstance(block, DocumentBlock):
                parts.append(f"{role}: [document attachment omitted for compaction]")

    return "\n\n".join(parts).strip()


def _fallback_compaction(messages: list[Message], keep_recent: int) -> list[Message]:
    dropped = len(messages) - keep_recent
    recent = messages[-keep_recent:]
    marker = Message(
        role="user",
        content=[
            TextBlock(
                text=(
                    "Earlier conversation context was compacted, but a structured "
                    f"summary was unavailable. {dropped} earlier messages were removed."
                )
            )
        ],
    )
    return [marker] + recent
