"""Permission rules — auto-allow / auto-deny based on tool name + input pattern.

Stored in `~/.claude/settings.json` under the `permissions` key, same shape as
Claude Code. Three lists: `allow`, `ask`, `deny`. Each rule is either:
  - A bare tool name: `"Read"` → matches all Read calls
  - `"Tool(pattern)"`: `"Bash(git diff:*)"` → matches Bash calls where the
    command starts with `git diff`

Deny wins over allow (deny checked first). If nothing matches, fall back to
the tool's own `check_permissions()` decision.
"""
from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .cc_compat import CLAUDE_DIR

SETTINGS_PATH = CLAUDE_DIR / "settings.json"

Decision = Literal["allow", "ask", "deny", "none"]


@dataclass
class PermissionRules:
    allow: list[str]
    ask: list[str]
    deny: list[str]

    @classmethod
    def load(cls) -> "PermissionRules":
        if not SETTINGS_PATH.exists():
            return cls(allow=[], ask=[], deny=[])
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return cls(allow=[], ask=[], deny=[])
        perms = data.get("permissions") or {}
        return cls(
            allow=list(perms.get("allow") or []),
            ask=list(perms.get("ask") or []),
            deny=list(perms.get("deny") or []),
        )

    def evaluate(self, tool_name: str, input_dict: dict[str, Any]) -> Decision:
        """Return the matched decision or 'none' if no rule matches.

        Deny rules are checked first (safety-first). Then allow, then ask.
        """
        for pattern in self.deny:
            if _match_rule(pattern, tool_name, input_dict):
                return "deny"
        for pattern in self.allow:
            if _match_rule(pattern, tool_name, input_dict):
                return "allow"
        for pattern in self.ask:
            if _match_rule(pattern, tool_name, input_dict):
                return "ask"
        return "none"


_RULE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*)(?:\((.+)\))?$")


def _match_rule(rule: str, tool_name: str, input_dict: dict[str, Any]) -> bool:
    m = _RULE_RE.match(rule.strip())
    if m is None:
        return False
    rule_tool = m.group(1)
    rule_pattern = m.group(2)
    if rule_tool != tool_name:
        return False
    if rule_pattern is None:
        return True
    # The pattern format is tool-specific. For Bash the convention is
    # `command-prefix:*`. For file tools it's `absolute-path-glob`.
    if tool_name == "Bash":
        command = (input_dict.get("command") or "").strip()
        return fnmatch.fnmatchcase(command, rule_pattern) or command.startswith(
            rule_pattern.rstrip(":*").rstrip("*")
        )
    if tool_name in ("Read", "Write", "Edit", "NotebookEdit"):
        path = (input_dict.get("file_path") or input_dict.get("notebook_path") or "")
        return fnmatch.fnmatchcase(path, rule_pattern)
    if tool_name in ("Glob", "Grep", "LS"):
        path = (input_dict.get("path") or input_dict.get("pattern") or "")
        return fnmatch.fnmatchcase(path, rule_pattern)
    return False
