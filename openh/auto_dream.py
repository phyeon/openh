"""AutoDream: automatic memory consolidation daemon."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from .cc_compat import memory_dir as project_memory_dir
from .cc_compat import project_dir

SESSION_SCAN_INTERVAL_SECS = 10 * 60


@dataclass(slots=True)
class AutoDreamConfig:
    min_hours: float = 24.0
    min_sessions: int = 5


@dataclass(slots=True)
class ConsolidationState:
    last_consolidated_at: int | None = None
    lock_etag: str | None = None


@dataclass(slots=True)
class ConsolidationTask:
    prompt: str
    memory_dir: Path
    state_file: Path
    lock_file: Path


class AutoDream:
    def __init__(
        self,
        memory_dir: Path,
        conversations_dir: Path,
        config: AutoDreamConfig | None = None,
    ) -> None:
        self.config = config or AutoDreamConfig()
        self.memory_dir = memory_dir
        self.conversations_dir = conversations_dir
        self.lock_file = self.memory_dir / ".consolidation_lock"
        self.state_file = self.memory_dir / ".consolidation_state.json"

    @classmethod
    def for_project(cls, cwd: str) -> "AutoDream":
        return cls(project_memory_dir(cwd), project_dir(cwd))

    async def maybe_trigger(self) -> ConsolidationTask | None:
        state = await self.load_state()
        if not await self.should_consolidate(state):
            return None
        await self.acquire_lock()
        return ConsolidationTask(
            prompt=self.consolidation_prompt(),
            memory_dir=self.memory_dir,
            state_file=self.state_file,
            lock_file=self.lock_file,
        )

    async def should_consolidate(self, state: ConsolidationState) -> bool:
        if not self.time_gate_passes(state):
            return False
        if not await self.session_gate_passes(state):
            return False
        if not await self.lock_gate_passes():
            return False
        return True

    def time_gate_passes(self, state: ConsolidationState) -> bool:
        if state.last_consolidated_at is None:
            return True
        elapsed_hours = (int(time.time()) - int(state.last_consolidated_at)) / 3600.0
        return elapsed_hours >= self.config.min_hours

    async def session_gate_passes(self, state: ConsolidationState) -> bool:
        last_secs = int(state.last_consolidated_at or 0)
        if not self.conversations_dir.exists():
            return False

        count = 0
        for path in self.conversations_dir.glob("*.jsonl"):
            try:
                mtime = int(path.stat().st_mtime)
            except OSError:
                continue
            if mtime > last_secs:
                count += 1
                if count >= self.config.min_sessions:
                    return True
        return False

    async def lock_gate_passes(self) -> bool:
        if not self.lock_file.exists():
            return True
        try:
            age_secs = int(time.time() - self.lock_file.stat().st_mtime)
        except OSError:
            return True
        return age_secs > 3600

    async def acquire_lock(self) -> None:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock_file.write_text(str(int(time.time())), encoding="utf-8")

    async def release_lock(self) -> None:
        try:
            self.lock_file.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    async def update_state(self, state: ConsolidationState) -> None:
        state.last_consolidated_at = int(time.time())
        payload = {
            "last_consolidated_at": state.last_consolidated_at,
            "lock_etag": state.lock_etag,
        }
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    async def load_state(self) -> ConsolidationState:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return ConsolidationState()
        return ConsolidationState(
            last_consolidated_at=_int_or_none(data.get("last_consolidated_at")),
            lock_etag=_str_or_none(data.get("lock_etag")),
        )

    @staticmethod
    async def finish_consolidation(task: ConsolidationTask) -> None:
        dreamer = AutoDream(task.memory_dir, task.memory_dir.parent)
        state = ConsolidationState(last_consolidated_at=None, lock_etag=None)
        await dreamer.update_state(state)
        try:
            await dreamer.release_lock()
        except Exception:
            pass

    def consolidation_prompt(self) -> str:
        return f"""# Dream: Memory Consolidation

You are performing a dream — a reflective pass over your memory files. Synthesize what you have learned recently into durable, well-organized memories so that future sessions can orient quickly.

Memory directory: `{self.memory_dir}`

Session transcripts: `{self.conversations_dir}` (large JSONL files — grep narrowly, do not read whole files)

---

## Phase 1 — Orient

- `ls` the memory directory to see what already exists
- Read `MEMORY.md` to understand the current index
- Skim existing topic files so you improve them rather than creating duplicates

## Phase 2 — Gather recent signal

Look for new information worth persisting:

1. **Daily logs** (`logs/YYYY/MM/YYYY-MM-DD.md`) if present
2. **Existing memories that drifted** — facts that contradict what you see now
3. **Transcript search** — grep narrowly for specific terms:
   `grep -rn "<narrow term>" {self.conversations_dir}/ --include="*.jsonl" | tail -50`

Do not exhaustively read transcripts. Look only for things you already suspect matter.

## Phase 3 — Consolidate

For each thing worth remembering, write or update a memory file. Focus on:
- Merging new signal into existing topic files rather than creating near-duplicates
- Converting relative dates to absolute dates
- Deleting contradicted facts

## Phase 4 — Prune and index

Update `MEMORY.md` so it stays under 200 lines and ~25 KB. It is an **index**, not a dump.
Each entry: `- [Title](file.md) — one-line hook`

- Remove pointers to stale, wrong, or superseded memories
- Shorten verbose entries; move detail into topic files
- Add pointers to newly important memories
- Resolve contradictions

---

Return a brief summary of what you consolidated, updated, or pruned. If nothing changed, say so.

**Tool constraints for this run:** Use only read-only Bash commands (ls, find, grep, cat, stat, wc, head, tail). Anything that writes, redirects to a file, or modifies state will be denied.
"""


def _int_or_none(value: object) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
