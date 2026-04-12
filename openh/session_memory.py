"""Automatic session-memory extraction and persistence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .messages import Message, TextBlock, TextDelta, ToolUseBlock, Usage
from .providers.base import Provider

MIN_MESSAGES_TO_EXTRACT = 20
MIN_TOOL_CALLS_BETWEEN_EXTRACTIONS = 3
SECTION_HEADER = "## Auto-extracted memories"

EXTRACTION_SYSTEM_PROMPT = (
    "You are a memory extraction assistant. Identify only stable, genuinely useful facts "
    "from a coding session that should be remembered for future work. "
    "Be concise, precise, and skip transient details."
)


@dataclass
class ExtractedMemory:
    content: str
    category: str
    confidence: float

    @property
    def label(self) -> str:
        mapping = {
            "user_preference": "user-preference",
            "project_fact": "project-fact",
            "code_pattern": "code-pattern",
            "decision": "decision",
            "constraint": "constraint",
        }
        return mapping.get(self.category, "project-fact")


def count_visible_messages(messages: list[Message]) -> int:
    count = 0
    for message in messages:
        if _message_text(message):
            count += 1
    return count


def count_tool_calls(messages: list[Message]) -> int:
    total = 0
    for message in messages:
        if message.role != "assistant":
            continue
        total += sum(1 for block in message.content if isinstance(block, ToolUseBlock))
    return total


def should_extract(
    messages: list[Message],
    *,
    last_extracted_message_count: int = 0,
    last_extracted_tool_call_count: int = 0,
    force: bool = False,
) -> bool:
    visible_count = count_visible_messages(messages)
    if visible_count < MIN_MESSAGES_TO_EXTRACT:
        return False

    last_assistant = next((message for message in reversed(messages) if message.role == "assistant"), None)
    if last_assistant is not None and any(
        isinstance(block, ToolUseBlock) for block in last_assistant.content
    ):
        return False

    total_tool_calls = count_tool_calls(messages)
    new_visible = visible_count - max(0, last_extracted_message_count)
    new_tool_calls = total_tool_calls - max(0, last_extracted_tool_call_count)

    if new_visible <= 0 and new_tool_calls <= 0:
        return False
    if force:
        return True
    return new_tool_calls >= MIN_TOOL_CALLS_BETWEEN_EXTRACTIONS


async def extract_memories(
    messages: list[Message],
    provider: Provider,
    cwd: str,
) -> tuple[list[ExtractedMemory], Usage]:
    transcript = _build_transcript(messages)
    if not transcript.strip():
        return [], Usage(input_tokens=0, output_tokens=0)

    prompt = _build_extraction_prompt(transcript, cwd)
    response_parts: list[str] = []
    usage = Usage(input_tokens=0, output_tokens=0)
    extraction_messages = [Message(role="user", content=[TextBlock(text=prompt)])]

    async for event in provider.stream(
        messages=extraction_messages,
        system=EXTRACTION_SYSTEM_PROMPT,
        tools=[],
    ):
        if isinstance(event, TextDelta):
            response_parts.append(event.text)
        elif isinstance(event, Usage):
            usage.input_tokens += event.input_tokens
            usage.output_tokens += event.output_tokens
            usage.cache_creation_input_tokens += event.cache_creation_input_tokens
            usage.cache_read_input_tokens += event.cache_read_input_tokens

    return _parse_response("".join(response_parts)), usage


async def persist_memories(memories: list[ExtractedMemory], target_path: Path) -> None:
    if not memories:
        return

    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing = target_path.read_text(encoding="utf-8")
    except OSError:
        existing = ""

    date_str = datetime.now().strftime("%Y-%m-%d")
    block_lines = [f"\n### Session memories - {date_str}\n"]
    for memory in memories:
        block_lines.append(
            f"- **[{memory.label}]** {memory.content} *(confidence: {round(memory.confidence * 100):.0f}%)*"
        )
    new_block = "\n".join(block_lines) + "\n"

    if SECTION_HEADER in existing:
        section_pos = existing.find(SECTION_HEADER)
        if section_pos >= 0:
            after_header = existing[section_pos + len(SECTION_HEADER):]
            next_section = after_header.find("\n## ")
            section_end = (
                section_pos + len(SECTION_HEADER) + next_section
                if next_section >= 0
                else len(existing)
            )
            updated = existing[:section_end] + new_block + existing[section_end:]
        else:
            updated = existing
    else:
        updated = existing
        if updated and not updated.endswith("\n"):
            updated += "\n"
        updated += f"\n{SECTION_HEADER}\n"
        updated += new_block.lstrip("\n")

    target_path.write_text(updated, encoding="utf-8")


def project_agents_path(cwd: str) -> Path:
    return Path(cwd) / ".claurst" / "AGENTS.md"


def _build_transcript(messages: list[Message]) -> str:
    parts: list[str] = []
    for message in messages:
        text = _message_text(message)
        if not text:
            continue
        role_label = "Human" if message.role == "user" else "Assistant"
        parts.append(f"{role_label}: {text}")
    return "\n\n".join(parts)


def _message_text(message: Message) -> str:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            text = block.text.strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _build_extraction_prompt(transcript: str, cwd: str) -> str:
    return (
        f"Please analyze the following coding-session transcript for `{cwd}` and extract only stable, "
        "future-useful memories.\n\n"
        "For each memory, output a line in exactly this format:\n"
        "MEMORY: <category> | <confidence 0-10> | <concise fact>\n\n"
        "Allowed categories:\n"
        "- user_preference\n"
        "- project_fact\n"
        "- code_pattern\n"
        "- decision\n"
        "- constraint\n\n"
        "Only output MEMORY lines. If nothing is worth remembering, output nothing.\n\n"
        f"<conversation>\n{transcript}\n</conversation>"
    )


def _parse_response(raw: str) -> list[ExtractedMemory]:
    memories: list[ExtractedMemory] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("MEMORY:"):
            continue
        parts = [part.strip() for part in line[len("MEMORY:"):].split("|", 2)]
        if len(parts) != 3:
            continue
        category, confidence_raw, content = parts
        if not content:
            continue
        try:
            confidence = max(0.0, min(float(confidence_raw) / 10.0, 1.0))
        except ValueError:
            confidence = 0.5
        memories.append(
            ExtractedMemory(
                content=content,
                category=category.lower(),
                confidence=confidence,
            )
        )
    return memories
