"""Conversation auto-compact: summarize old turns when the context grows too large.

When the running input-token estimate exceeds a threshold, we ask the current
provider to summarize everything up to the last N turns into a single user
message, then replace the old turns with that summary. The most recent N turns
are kept verbatim so the model still has immediate context.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .messages import Message, TextBlock

if TYPE_CHECKING:
    from .providers.base import Provider


COMPACT_SYSTEM_PROMPT = """You are a conversation summarizer. The user will paste a chat transcript between a user and an AI coding assistant. Produce a dense, factual summary covering:

1. What the user was trying to accomplish (goals, tasks)
2. Key decisions made and their justifications
3. Files that were read, created, or edited (with paths)
4. Commands that were run and their outcomes
5. Known open issues, errors, or incomplete items
6. Any constraints the user specified

Do not speculate. Stay under 600 words. Use markdown with short bullet sections. Start with a one-line context header."""


def estimate_tokens(messages: list[Message]) -> int:
    """Rough char/4 estimate of total tokens. Good enough for triggering compaction."""
    total = 0
    for m in messages:
        for b in m.content:
            if isinstance(b, TextBlock):
                total += len(b.text)
            else:
                # tool_use / tool_result — approximate by str() length
                total += len(str(b.to_dict() if hasattr(b, "to_dict") else b))
    return total // 4


def should_compact(messages: list[Message], threshold_tokens: int | None = None) -> bool:
    if threshold_tokens is None:
        from .config import AUTO_COMPACT_THRESHOLD
        threshold_tokens = AUTO_COMPACT_THRESHOLD
    return estimate_tokens(messages) > threshold_tokens


def _transcript(messages: list[Message]) -> str:
    lines: list[str] = []
    for m in messages:
        role = m.role
        for b in m.content:
            if isinstance(b, TextBlock):
                lines.append(f"[{role}] {b.text}")
            else:
                d = b.to_dict() if hasattr(b, "to_dict") else {}
                if d.get("type") == "tool_use":
                    lines.append(f"[{role}] TOOL_CALL {d.get('name')}({d.get('input')})")
                elif d.get("type") == "tool_result":
                    content = d.get("content", "")
                    if len(content) > 500:
                        content = content[:500] + "…"
                    err = " (error)" if d.get("is_error") else ""
                    lines.append(f"[{role}] TOOL_RESULT{err}: {content}")
    return "\n".join(lines)


async def compact_messages(
    messages: list[Message],
    provider: "Provider",
    keep_recent: int = 6,
) -> list[Message]:
    """Return a new message list with old messages replaced by a summary block.

    Keeps the last `keep_recent` messages verbatim.
    """
    if len(messages) <= keep_recent:
        return messages

    old = messages[:-keep_recent]
    recent = messages[-keep_recent:]

    transcript = _transcript(old)
    summary_prompt = f"Summarize this conversation transcript:\n\n{transcript}"

    # Use the provider to summarize. Stream and collect text.
    from .messages import TextDelta
    summary_parts: list[str] = []
    async for event in provider.stream(
        messages=[Message(role="user", content=[TextBlock(text=summary_prompt)])],
        system=COMPACT_SYSTEM_PROMPT,
        tools=[],
    ):
        if isinstance(event, TextDelta):
            summary_parts.append(event.text)

    summary_text = "".join(summary_parts).strip() or "[summary unavailable]"

    summary_marker = Message(
        role="user",
        content=[
            TextBlock(
                text=f"[Prior conversation summary]\n\n{summary_text}\n\n[End of summary. The following messages are the continuation of the conversation.]"
            )
        ],
    )

    return [summary_marker] + recent
