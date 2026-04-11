"""Hook system.

Hooks are shell commands that run in response to events (tool calls, user
prompt submission, session start/end). Configuration lives at
~/.openh/hooks.json:

{
  "PreToolUse": [
    {"matcher": "Bash", "command": "echo 'about to run bash'"}
  ],
  "PostToolUse": [
    {"matcher": "Edit|Write", "command": "./scripts/format.sh"}
  ],
  "UserPromptSubmit": [
    {"command": "echo submitted"}
  ]
}

- matcher is a regex tested against tool name. If omitted, matches all.
- command is run via /bin/sh with the hook event metadata as JSON on stdin.
- If command exits with status 2, the tool call is blocked.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HOOKS_PATH = Path.home() / ".openh" / "hooks.json"

HookEvent = str  # "PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionStart", "SessionEnd"


@dataclass
class HookSpec:
    event: HookEvent
    matcher: re.Pattern[str] | None
    command: str


@dataclass
class HookResult:
    exit_code: int
    stdout: str
    stderr: str
    block: bool


def load_hooks() -> list[HookSpec]:
    if not HOOKS_PATH.exists():
        return []
    try:
        data = json.loads(HOOKS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    specs: list[HookSpec] = []
    for event, entries in (data.items() if isinstance(data, dict) else []):
        for entry in entries or []:
            matcher_str = entry.get("matcher")
            matcher = re.compile(matcher_str) if matcher_str else None
            command = entry.get("command", "")
            if not command:
                continue
            specs.append(HookSpec(event=event, matcher=matcher, command=command))
    return specs


async def fire_hook(
    specs: list[HookSpec],
    event: HookEvent,
    payload: dict[str, Any],
) -> HookResult | None:
    """Fire all hooks matching `event` with payload piped as JSON on stdin.

    Returns the last HookResult (or None if no hooks fired). If any hook exits
    with status 2, block=True is set.
    """
    last: HookResult | None = None
    tool_name = payload.get("tool_name", "") if isinstance(payload, dict) else ""
    for spec in specs:
        if spec.event != event:
            continue
        if spec.matcher is not None and not spec.matcher.search(tool_name or ""):
            continue
        try:
            proc = await asyncio.create_subprocess_shell(
                spec.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdin_data = json.dumps({"event": event, **payload}).encode("utf-8")
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(input=stdin_data), timeout=30
            )
        except Exception as exc:  # noqa: BLE001
            last = HookResult(exit_code=-1, stdout="", stderr=str(exc), block=False)
            continue
        last = HookResult(
            exit_code=proc.returncode or 0,
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            block=(proc.returncode == 2),
        )
        if last.block:
            return last
    return last
