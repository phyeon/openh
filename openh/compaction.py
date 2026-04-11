"""Conversation auto-compact: trim old turns when the context grows too large.

Like Claude Code: no LLM summarization, just drop the oldest messages and
keep the most recent ones. A system marker is inserted so the model knows
the conversation was truncated.
"""
from __future__ import annotations

from .messages import Message, TextBlock


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


def should_compact(messages: list[Message], threshold_tokens: int | None = None) -> bool:
    from .config import AUTO_COMPACT_THRESHOLD, MAX_CONVERSATION_MESSAGES
    if threshold_tokens is None:
        threshold_tokens = AUTO_COMPACT_THRESHOLD
    if len(messages) > MAX_CONVERSATION_MESSAGES:
        return True
    return estimate_tokens(messages) > threshold_tokens


async def compact_messages(
    messages: list[Message],
    provider: object = None,  # unused, kept for signature compat
    keep_recent: int = 20,
) -> list[Message]:
    """Trim old messages, keeping the last `keep_recent`.

    Inserts a marker so the model knows earlier context was dropped.
    No LLM call — instant and free.
    """
    if len(messages) <= keep_recent:
        return messages

    dropped = len(messages) - keep_recent
    recent = messages[-keep_recent:]

    marker = Message(
        role="user",
        content=[
            TextBlock(
                text=f"[Conversation compacted: {dropped} earlier messages were removed to fit context. Continue from here.]"
            )
        ],
    )
    ack = Message(
        role="assistant",
        content=[TextBlock(text="Understood. Continuing from the recent context.")],
    )

    return [marker, ack] + recent
