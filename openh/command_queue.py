"""Priority command queue for engine-level message injection."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import heapq
import time

from .messages import Message, TextBlock


class CommandPriority(IntEnum):
    INTERRUPT = 3
    HIGH = 2
    NORMAL = 1
    LOW = 0


@dataclass(order=True)
class _QueueEntry:
    sort_key: tuple[int, float]
    kind: str = field(compare=False)
    text: str = field(compare=False)


class CommandQueue:
    def __init__(self) -> None:
        self._heap: list[_QueueEntry] = []

    def push_user_message(
        self,
        text: str,
        priority: CommandPriority = CommandPriority.NORMAL,
    ) -> None:
        self._push("user", text, priority)

    def push_system_message(
        self,
        text: str,
        priority: CommandPriority = CommandPriority.NORMAL,
    ) -> None:
        self._push("system", text, priority)

    def _push(self, kind: str, text: str, priority: CommandPriority) -> None:
        content = (text or "").strip()
        if not content:
            return
        # heapq is min-first, so negate priority and timestamp for higher-priority / older-first.
        heapq.heappush(
            self._heap,
            _QueueEntry(
                sort_key=(-int(priority), time.time()),
                kind=kind,
                text=content,
            ),
        )

    def is_empty(self) -> bool:
        return not self._heap

    def drain_to_messages(self) -> list[Message]:
        out: list[Message] = []
        while self._heap:
            item = heapq.heappop(self._heap)
            if item.kind == "system":
                out.append(
                    Message(
                        role="user",
                        content=[TextBlock(text=f"[System]: {item.text}")],
                    )
                )
            else:
                out.append(Message(role="user", content=[TextBlock(text=item.text)]))
        return out
