"""Conversation compaction helpers mirroring the public Claude Code engine."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from .messages import (
    Block,
    DocumentBlock,
    ImageBlock,
    Message,
    MessageStop,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)

AUTOCOMPACT_BUFFER_TOKENS = 13_000
WARNING_THRESHOLD_BUFFER_TOKENS = 20_000
KEEP_RECENT_MESSAGES = 10
AUTOCOMPACT_TRIGGER_FRACTION = 0.90
MAX_CONSECUTIVE_FAILURES = 3
WARNING_PCT = 0.80
CRITICAL_PCT = 0.95
MICRO_COMPACT_TRIGGER_FRACTION = 0.75
REACTIVE_COMPACT_THRESHOLD = 0.90
CONTEXT_COLLAPSE_THRESHOLD = 0.97

NO_TOOLS_PREAMBLE = """CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

- Do NOT use Read, Bash, Grep, Glob, Edit, Write, or ANY other tool.
- You already have all the context you need in the conversation above.
- Tool calls will be REJECTED and will waste your only turn - you will fail the task.
- Your entire response must be plain text: an <analysis> block followed by a <summary> block.

"""

NO_TOOLS_TRAILER = """

REMINDER: Do NOT call any tools. Respond with plain text only - an <analysis> block followed by a <summary> block. Tool calls will be rejected and you will fail the task."""

BASE_COMPACT_PROMPT = """Your task is to create a detailed summary of the conversation so far, paying close attention to the user's explicit requests and your previous actions.
This summary should be thorough in capturing technical details, code patterns, and architectural decisions that would be essential for continuing development work without losing context.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your thoughts and ensure you've covered all necessary points. In your analysis process:

1. Chronologically analyze each message and section of the conversation. For each section thoroughly identify:
   - The user's explicit requests and intents
   - Your approach to addressing the user's requests
   - Key decisions, technical concepts and code patterns
   - Specific details like:
     - file names
     - full code snippets
     - function signatures
     - file edits
   - Errors that you ran into and how you fixed them
   - Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
2. Double-check for technical accuracy and completeness, addressing each required element thoroughly.

Your summary should include the following sections:

1. Primary Request and Intent: Capture all of the user's explicit requests and intents in detail
2. Key Technical Concepts: List all important technical concepts, technologies, and frameworks discussed.
3. Files and Code Sections: Enumerate specific files and code sections examined, modified, or created. Pay special attention to the most recent messages and include full code snippets where applicable and include a summary of why this file read or edit is important.
4. Errors and fixes: List all errors that you ran into, and how you fixed them. Pay special attention to specific user feedback that you received, especially if the user told you to do something differently.
5. Problem Solving: Document problems solved and any ongoing troubleshooting efforts.
6. All user messages: List ALL user messages that are not tool results. These are critical for understanding the users' feedback and changing intent.
7. Pending Tasks: Outline any pending tasks that you have explicitly been asked to work on.
8. Current Work: Describe in detail precisely what was being worked on immediately before this summary request, paying special attention to the most recent messages from both user and assistant. Include file names and code snippets where applicable.
9. Optional Next Step: List the next step that you will take that is related to the most recent work you were doing. IMPORTANT: ensure that this step is DIRECTLY in line with the user's most recent explicit requests, and the task you were working on immediately before this summary request. If your last task was concluded, then only list next steps if they are explicitly in line with the users request. Do not start on tangential requests or really old requests that were already completed without confirming with the user first.
                       If there is a next step, include direct quotes from the most recent conversation showing exactly what task you were working on and where you left off. This should be verbatim to ensure there's no drift in task interpretation.

Format your output as:

<analysis>
[Your thought process, ensuring all points are covered thoroughly and accurately]
</analysis>

<summary>
1. Primary Request and Intent:
   [Detailed description]

2. Key Technical Concepts:
   - [Concept 1]
   - [Concept 2]

3. Files and Code Sections:
   - [File Name 1]
      - [Summary of why this file is important]
      - [Summary of the changes made to this file, if any]
      - [Important Code Snippet]

4. Errors and fixes:
    - [Detailed description of error 1]:
      - [How you fixed the error]

5. Problem Solving:
   [Description of solved problems and ongoing troubleshooting]

6. All user messages:
    - [Detailed non tool use user message]

7. Pending Tasks:
   - [Task 1]

8. Current Work:
   [Precise description of current work]

9. Optional Next Step:
   [Optional Next step to take]
</summary>

Please provide your summary based on the conversation so far, following this structure and ensuring precision and thoroughness in your response."""

COMPACT_SUMMARY_SYSTEM = (
    "You are a helpful assistant that creates concise yet thorough conversation summaries. "
    "Preserve all technical details, file names, code snippets, and decisions that would "
    "be important for continuing the work. Follow the structured format exactly."
)


@dataclass
class AutoCompactState:
    compaction_count: int = 0
    consecutive_failures: int = 0
    disabled: bool = False

    def on_success(self) -> None:
        self.compaction_count += 1
        self.consecutive_failures = 0

    def on_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            self.disabled = True


class TokenWarningState(str, Enum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class MessageGroup:
    messages: list[Message]
    topic_hint: str | None
    token_estimate: int


@dataclass
class MicroCompactConfig:
    trigger_threshold: float = MICRO_COMPACT_TRIGGER_FRACTION
    keep_recent_messages: int = KEEP_RECENT_MESSAGES
    summary_target_tokens: int = 2048


@dataclass(frozen=True)
class CompactTrigger:
    kind: str
    tokens_used: int | None = None
    context_limit: int | None = None

    @classmethod
    def token_threshold(
        cls,
        tokens_used: int,
        context_limit: int,
    ) -> "CompactTrigger":
        return cls(
            kind="token_threshold",
            tokens_used=tokens_used,
            context_limit=context_limit,
        )

    @classmethod
    def forced(cls) -> "CompactTrigger":
        return cls(kind="forced")


@dataclass
class CompactResult:
    messages: list[Message]
    summary: str
    tokens_freed: int


def estimate_block_chars(block: object) -> int:
    if isinstance(block, TextBlock):
        return len(block.text)
    if isinstance(block, ToolUseBlock):
        return len(block.name) + len(json.dumps(block.input or {}, ensure_ascii=False))
    if isinstance(block, ToolResultBlock):
        return len(block.content or "")
    if isinstance(block, (ImageBlock, DocumentBlock)):
        return 200
    return 200


def estimate_tokens(messages: list[Message]) -> int:
    """Rough token estimate: chars/4 padded by 4/3."""
    chars = sum(
        estimate_block_chars(block)
        for message in messages
        for block in message.content
    )
    if chars <= 0:
        return 0
    return (chars // 4) * 4 // 3


def extract_topic_hint(messages: list[Message]) -> str | None:
    for message in messages:
        for block in message.content:
            if not isinstance(block, ToolUseBlock):
                continue
            file_path = str((block.input or {}).get("file_path") or "").strip()
            if file_path:
                return file_path
            command = str((block.input or {}).get("command") or "").strip()
            if command:
                return command.split(maxsplit=1)[0]
            return block.name
    return None


def group_messages_for_compact(messages: list[Message]) -> list[MessageGroup]:
    groups: list[MessageGroup] = []
    current: list[Message] = []
    for message in messages:
        current.append(_copy_message(message))
        if message.role == "assistant":
            groups.append(
                MessageGroup(
                    messages=list(current),
                    topic_hint=extract_topic_hint(current),
                    token_estimate=estimate_tokens(current),
                )
            )
            current.clear()
    if current:
        groups.append(
            MessageGroup(
                messages=list(current),
                topic_hint=extract_topic_hint(current),
                token_estimate=estimate_tokens(current),
            )
        )
    return groups


def context_window_for_model(model: str) -> int:
    name = (model or "").lower()
    if (
        "opus-4" in name
        or "sonnet-4" in name
        or "haiku-4" in name
        or "claude-3-5" in name
        or "claude-3.5" in name
    ):
        return 200_000
    return 100_000


def calculate_token_warning_state(input_tokens: int, model: str) -> TokenWarningState:
    window = context_window_for_model(model)
    pct = float(input_tokens or 0) / float(window or 1)
    if pct >= CRITICAL_PCT:
        return TokenWarningState.CRITICAL
    if pct >= WARNING_PCT or (window - int(input_tokens or 0)) <= WARNING_THRESHOLD_BUFFER_TOKENS:
        return TokenWarningState.WARNING
    return TokenWarningState.OK


def should_auto_compact(
    input_tokens: int,
    model: str,
    state: AutoCompactState,
) -> bool:
    if state.disabled:
        return False
    window = context_window_for_model(model)
    threshold = int(window * AUTOCOMPACT_TRIGGER_FRACTION)
    return int(input_tokens or 0) >= threshold


def should_compact(tokens_used: int, context_limit: int) -> bool:
    if int(context_limit or 0) <= 0:
        return False
    threshold = int(context_limit * REACTIVE_COMPACT_THRESHOLD)
    return int(tokens_used or 0) >= threshold


def should_context_collapse(tokens_used: int, context_limit: int) -> bool:
    if int(context_limit or 0) <= 0:
        return False
    threshold = int(context_limit * CONTEXT_COLLAPSE_THRESHOLD)
    return int(tokens_used or 0) >= threshold


def get_compact_prompt(custom_instructions: str | None = None) -> str:
    prompt = f"{NO_TOOLS_PREAMBLE}{BASE_COMPACT_PROMPT}"
    trimmed = (custom_instructions or "").strip()
    if trimmed:
        prompt += f"\n\nAdditional Instructions:\n{trimmed}"
    prompt += NO_TOOLS_TRAILER
    return prompt


async def compact_messages(
    messages: list[Message],
    provider: object = None,
    keep_recent: int = KEEP_RECENT_MESSAGES,
    session: "AgentSession | None" = None,
    strategy: str = "full",
) -> list[Message]:
    """Compatibility wrapper for manual compaction entry points."""
    if len(messages) <= keep_recent + 1:
        return messages

    if provider is None or not hasattr(provider, "stream"):
        return _fallback_compaction(messages, keep_recent)

    model = str(getattr(provider, "model", "") or "")
    try:
        if strategy == "collapse":
            return (await context_collapse(messages, provider, model, session=session)).messages
        if strategy == "reactive":
            return (await reactive_compact(messages, provider, model, session=session)).messages
        if strategy == "micro":
            result = await micro_compact_if_needed(
                provider,
                messages,
                estimate_tokens(messages),
                model,
                session=session,
            )
            return result if result is not None else messages
        return await compact_conversation(provider, messages, model, session=session)
    except Exception:
        return _fallback_compaction(messages, keep_recent)


async def compact_conversation(
    provider: object,
    messages: list[Message],
    model: str,
    session: "AgentSession | None" = None,
) -> list[Message]:
    total = len(messages)
    if total <= KEEP_RECENT_MESSAGES + 1:
        return [_copy_message(message) for message in messages]
    split_at = max(0, total - KEEP_RECENT_MESSAGES)
    return await _summarise_head(
        messages,
        split_at,
        provider,
        model=model,
        max_summary_tokens=20_000,
        session=session,
    )


async def auto_compact_if_needed(
    provider: object,
    messages: list[Message],
    input_tokens: int,
    model: str,
    state: AutoCompactState,
    session: "AgentSession | None" = None,
) -> list[Message] | None:
    if not should_auto_compact(input_tokens, model, state):
        return None
    try:
        compacted = await compact_conversation(provider, messages, model, session=session)
    except Exception:
        state.on_failure()
        return None
    state.on_success()
    return compacted


async def micro_compact_if_needed(
    provider: object,
    messages: list[Message],
    input_tokens: int,
    model: str,
    config: MicroCompactConfig | None = None,
    session: "AgentSession | None" = None,
) -> list[Message] | None:
    cfg = config or MicroCompactConfig()
    window = context_window_for_model(model)
    pct_used = float(input_tokens or 0) / float(window or 1)
    if pct_used < cfg.trigger_threshold:
        return None
    total = len(messages)
    if total <= cfg.keep_recent_messages + 1:
        return None
    split_at = max(0, total - cfg.keep_recent_messages)
    try:
        return await _summarise_head(
            messages,
            split_at,
            provider,
            model=model,
            max_summary_tokens=cfg.summary_target_tokens,
            session=session,
        )
    except Exception:
        return None


def _adjust_split_for_tool_pairs(messages: list[Message], split_at: int) -> int:
    """Shrink ``split_at`` until ``messages[split_at:]`` has no orphan tool_result
    blocks (i.e. every tool_result in the tail has its matching tool_use in the
    tail too).  Without this, a pair can be cut by compaction, leaving the tail
    starting with a dangling tool_result that every provider will reject.

    Worst case: returns 0, i.e. the tail becomes the full conversation and no
    compaction happens — safer than producing an invalid message sequence.
    """
    if split_at <= 0 or split_at >= len(messages):
        return split_at
    while split_at > 0:
        known_ids: set[str] = set()
        orphan = False
        for m in messages[split_at:]:
            if m.role == "assistant":
                for b in m.content:
                    if isinstance(b, ToolUseBlock):
                        known_ids.add(b.id)
                continue
            for b in m.content:
                if isinstance(b, ToolResultBlock) and b.tool_use_id not in known_ids:
                    orphan = True
                    break
            if orphan:
                break
        if not orphan:
            return split_at
        split_at -= 1
    return split_at


def sanitize_orphan_tool_results(messages: list[Message]) -> list[Message]:
    """Drop tool_result blocks whose matching tool_use is missing from the
    preceding conversation.  Used as a final safety net before sending to the
    provider — protects against sessions that were already broken by earlier
    buggy compaction, manual edits, or provider-switch edge cases.

    Empty user messages that result from dropping are skipped entirely.
    """
    known_ids: set[str] = set()
    new_messages: list[Message] = []
    for m in messages:
        if m.role == "assistant":
            for b in m.content:
                if isinstance(b, ToolUseBlock):
                    known_ids.add(b.id)
            new_messages.append(m)
            continue
        new_blocks: list[Block] = []
        for b in m.content:
            if isinstance(b, ToolResultBlock) and b.tool_use_id not in known_ids:
                continue
            new_blocks.append(b)
        if new_blocks:
            new_messages.append(Message(role=m.role, content=new_blocks, uuid=m.uuid))
    return new_messages


async def _summarise_head(
    messages: list[Message],
    split_at: int,
    provider: object,
    *,
    model: str,
    max_summary_tokens: int,
    session: "AgentSession | None" = None,
) -> list[Message]:
    if split_at == 0:
        return [_copy_message(message) for message in messages]

    # Avoid cutting a tool_use/tool_result pair across the compaction boundary.
    split_at = _adjust_split_for_tool_pairs(messages, split_at)
    if split_at == 0:
        return [_copy_message(message) for message in messages]

    head = messages[:split_at]
    tail = messages[split_at:]
    transcript = _messages_to_transcript(head)
    original_count = len(head)
    original_tokens = estimate_tokens(head)
    prompt = (
        f"{get_compact_prompt(None)}\n\n"
        f"<conversation_to_summarize original_messages=\"{original_count}\" "
        f"estimated_tokens=\"{original_tokens}\">\n{transcript}\n"
        f"</conversation_to_summarize>"
    )

    stream = provider.stream(
        messages=[Message(role="user", content=[TextBlock(text=prompt)])],
        system=COMPACT_SUMMARY_SYSTEM,
        tools=[],
        max_tokens=max_summary_tokens,
    )

    chunks: list[str] = []
    async for event in stream:
        if isinstance(event, TextDelta):
            chunks.append(event.text)
        elif isinstance(event, Usage):
            if session is not None:
                session.add_tokens(
                    event.input_tokens,
                    event.output_tokens,
                    event.cache_creation_input_tokens,
                    event.cache_read_input_tokens,
                    model=getattr(provider, "model", model),
                    update_last_input=False,
                )
        elif isinstance(event, MessageStop):
            break

    raw_summary = "".join(chunks).strip()
    if not raw_summary:
        raise RuntimeError("Compact summary was empty")

    formatted_summary = format_compact_summary(raw_summary)
    compact_notice = Message(
        role="user",
        content=[
            TextBlock(
                text=(
                    "This session is being continued from a previous conversation that "
                    "ran out of context. The summary below covers the earlier portion "
                    f"of the conversation (originally {original_count} messages, "
                    f"~{original_tokens} tokens).\n\n{formatted_summary}"
                )
            )
        ],
    )
    new_messages = [compact_notice]
    new_messages.extend(_copy_message(message) for message in tail)
    return new_messages


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


def _message_text(message: Message) -> str:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock) and block.text.strip():
            parts.append(block.text.strip())
        elif isinstance(block, ToolResultBlock) and block.content.strip():
            parts.append(block.content.strip())
    return "\n".join(parts).strip()


def _messages_to_transcript(messages: list[Message]) -> str:
    parts: list[str] = []

    for msg in messages:
        role = "Human" if msg.role == "user" else "Assistant"
        for block in msg.content:
            if isinstance(block, TextBlock):
                if block.text.strip():
                    parts.append(f"{role}: {block.text.strip()}")
            elif isinstance(block, ToolUseBlock):
                payload = json.dumps(block.input or {}, ensure_ascii=False)
                parts.append(
                    f"[Tool Call: {block.name} (id={block.id})]\nInput: {payload}"
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


def _copy_message(message: Message) -> Message:
    return Message(role=message.role, content=list(message.content), uuid=message.uuid)


def _strip_images(messages: list[Message]) -> list[Message]:
    stripped: list[Message] = []
    for message in messages:
        blocks = [block for block in message.content if not isinstance(block, ImageBlock)]
        if not blocks:
            blocks = [TextBlock(text="[image removed for compaction]")]
        stripped.append(Message(role=message.role, content=blocks, uuid=message.uuid))
    return stripped


def snip_compact(messages: list[Message], keep_n_newest: int) -> tuple[list[Message], int]:
    total = len(messages)
    if total <= keep_n_newest + 1:
        return ([_copy_message(message) for message in messages], 0)
    snip_start = 1
    snip_end = max(1, total - keep_n_newest)
    if snip_start >= snip_end:
        return ([_copy_message(message) for message in messages], 0)
    snipped_tokens = estimate_tokens(messages[snip_start:snip_end])
    result = [_copy_message(messages[0])]
    result.extend(_copy_message(message) for message in messages[snip_end:])
    return (result, snipped_tokens)


def calculate_messages_to_keep_index(messages: list[Message], token_budget: int) -> int:
    if not messages:
        return 0

    accumulated = 0
    keep_from = len(messages)
    for index in range(len(messages) - 1, -1, -1):
        estimate = estimate_tokens([messages[index]])
        if accumulated + estimate > token_budget:
            keep_from = index + 1
            break
        accumulated += estimate
        keep_from = index
    return keep_from


async def reactive_compact(
    messages: list[Message],
    provider: object,
    model: str,
    session: "AgentSession | None" = None,
    recently_modified: list[str] | None = None,
) -> CompactResult:
    del recently_modified  # public Rust port currently passes an empty list here

    total = len(messages)
    if total == 0:
        return CompactResult(messages=[], summary="", tokens_freed=0)

    stripped = _strip_images(messages)
    split_at = max(0, total - KEEP_RECENT_MESSAGES)
    if split_at == 0:
        copied = [_copy_message(message) for message in messages]
        return CompactResult(messages=copied, summary="", tokens_freed=0)

    original_token_estimate = estimate_tokens(stripped[:split_at])
    new_messages = await _summarise_head(
        stripped,
        split_at,
        provider,
        model=model,
        max_summary_tokens=20_000,
        session=session,
    )
    summary_text = _message_text(new_messages[0]) if new_messages else ""
    tokens_after = estimate_tokens(new_messages)
    return CompactResult(
        messages=new_messages,
        summary=summary_text,
        tokens_freed=max(0, original_token_estimate - tokens_after),
    )


async def context_collapse(
    messages: list[Message],
    provider: object,
    model: str,
    session: "AgentSession | None" = None,
) -> CompactResult:
    del model

    total = len(messages)
    if total == 0:
        return CompactResult(messages=[], summary="", tokens_freed=0)

    original_tokens = estimate_tokens(messages)
    transcript_parts: list[str] = []
    for message in messages:
        role = "Human" if message.role == "user" else "Assistant"
        text = _message_text(message)
        if text:
            transcript_parts.append(f"{role}: {text}")
    transcript = "\n\n".join(transcript_parts).strip()
    collapse_prompt = (
        "EMERGENCY CONTEXT COLLAPSE - the conversation is at critical capacity.\n"
        "Produce an ULTRA-SHORT (max 500 words) emergency summary that captures:\n"
        "1. The user's most recent explicit request.\n"
        "2. The single most important decision made so far.\n"
        "3. Any file names or code snippets that are ESSENTIAL to continue.\n"
        "4. What was being worked on immediately before this collapse.\n"
        "Respond with plain text only - no XML tags, no tool calls.\n\n"
        f"<conversation>\n{transcript}\n</conversation>"
    )

    stream = provider.stream(
        messages=[Message(role="user", content=[TextBlock(text=collapse_prompt)])],
        system=(
            "You are a conversation summariser. Produce an emergency ultra-short "
            "summary as instructed. Plain text only."
        ),
        tools=[],
        max_tokens=1_000,
    )

    chunks: list[str] = []
    async for event in stream:
        if isinstance(event, TextDelta):
            chunks.append(event.text)
        elif isinstance(event, Usage):
            if session is not None:
                session.add_tokens(
                    event.input_tokens,
                    event.output_tokens,
                    event.cache_creation_input_tokens,
                    event.cache_read_input_tokens,
                    model=getattr(provider, "model", ""),
                    update_last_input=False,
                )
        elif isinstance(event, MessageStop):
            break

    summary_text = "".join(chunks).strip()
    if not summary_text:
        raise RuntimeError("Context-collapse summary was empty")

    collapse_notice = Message(
        role="user",
        content=[
            TextBlock(
                text=(
                    "[EMERGENCY CONTEXT COLLAPSE - conversation condensed to stay "
                    f"within limits]\n\n{summary_text}"
                )
            )
        ],
    )

    last_user = next(
        (_copy_message(message) for message in reversed(messages) if message.role == "user"),
        None,
    )
    new_messages = [collapse_notice]
    if last_user is not None:
        new_messages.append(last_user)
    return CompactResult(
        messages=new_messages,
        summary=summary_text,
        tokens_freed=max(0, original_tokens - estimate_tokens(new_messages)),
    )


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
    return [marker] + [_copy_message(message) for message in recent]


if TYPE_CHECKING:
    from .session import AgentSession
