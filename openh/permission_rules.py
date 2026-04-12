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
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from .cc_compat import OPENH_DIR
from .tools.base import PermissionLevel

SETTINGS_PATH = OPENH_DIR / "settings.json"

Decision = Literal["allow", "ask", "deny", "none"]


class PermissionMode(str, Enum):
    DEFAULT = "default"
    ACCEPT_EDITS = "accept_edits"
    BYPASS_PERMISSIONS = "bypass_permissions"
    PLAN = "plan"


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


def effective_permission_mode(session: Any) -> PermissionMode:
    raw = str(getattr(session, "permission_mode", "") or "").strip().lower()
    for mode in PermissionMode:
        if raw == mode.value:
            return mode
    if bool(getattr(session, "plan_mode", False)):
        return PermissionMode.PLAN
    return PermissionMode.DEFAULT


def derive_rule_pattern(tool_name: str, input_dict: dict[str, Any]) -> str:
    if tool_name == "Bash":
        command = str(input_dict.get("command") or "").strip()
        if command:
            return command + "*"
    if tool_name in ("Read", "Write", "Edit", "NotebookEdit"):
        path = str(
            input_dict.get("file_path")
            or input_dict.get("notebook_path")
            or ""
        ).strip()
        if path:
            return path
    if tool_name in ("Glob", "Grep", "LS"):
        path = str(input_dict.get("path") or input_dict.get("pattern") or "").strip()
        if path:
            return path
    if tool_name in ("WebFetch", "WebSearch"):
        value = str(input_dict.get("url") or input_dict.get("query") or "").strip()
        if value:
            return value
    return "*"


def session_override_matches(
    overrides: set[tuple[str, str]],
    tool_name: str,
    input_dict: dict[str, Any],
) -> bool:
    for override_tool, override_pattern in overrides:
        if override_tool != tool_name:
            continue
        if override_pattern == "*":
            return True
        rule = f"{tool_name}({override_pattern})"
        if _match_rule(rule, tool_name, input_dict):
            return True
    return False


def format_permission_reason(
    tool_name: str,
    input_dict: dict[str, Any],
    level: PermissionLevel,
) -> str:
    if level == PermissionLevel.EXECUTE:
        command = str(input_dict.get("command") or "").strip() or tool_name
        return f"{tool_name} wants to run: `{command}`\nThis will execute a shell command."
    if level == PermissionLevel.WRITE:
        target = str(
            input_dict.get("file_path")
            or input_dict.get("notebook_path")
            or input_dict.get("path")
            or input_dict.get("name")
            or tool_name
        ).strip()
        return f"{tool_name} wants to write to `{target}`\nThis will modify local state."
    if level == PermissionLevel.DANGEROUS:
        target = str(input_dict.get("command") or input_dict.get("path") or tool_name).strip()
        return f"{tool_name} wants dangerous access: `{target}`\nThis may affect the system outside the workspace."
    if level == PermissionLevel.READ_ONLY:
        target = str(
            input_dict.get("file_path")
            or input_dict.get("path")
            or input_dict.get("pattern")
            or input_dict.get("url")
            or input_dict.get("query")
            or tool_name
        ).strip()
        return f"{tool_name} wants to read: `{target}`"
    return ""


def evaluate_permission(
    session: Any,
    rules: PermissionRules,
    tool_name: str,
    input_dict: dict[str, Any],
    level: PermissionLevel,
) -> tuple[Decision, str]:
    mode = effective_permission_mode(session)

    if mode == PermissionMode.BYPASS_PERMISSIONS:
        return "allow", ""

    always_deny = getattr(session, "always_deny", set())
    if isinstance(always_deny, set) and session_override_matches(always_deny, tool_name, input_dict):
        return "deny", "permission denied by remembered user preference"

    rule_decision = rules.evaluate(tool_name, input_dict)
    if rule_decision == "deny":
        return "deny", f"permission denied by rule in {PermissionRules.__module__}"

    always_allow = getattr(session, "always_allow", set())
    if isinstance(always_allow, set) and session_override_matches(always_allow, tool_name, input_dict):
        return "allow", ""

    if rule_decision == "allow":
        return "allow", ""
    if rule_decision == "ask":
        return "ask", format_permission_reason(tool_name, input_dict, level)

    if mode == PermissionMode.ACCEPT_EDITS:
        return "allow", ""

    if level == PermissionLevel.FORBIDDEN:
        return "deny", "this action is unconditionally forbidden"

    if mode == PermissionMode.PLAN:
        if level in (PermissionLevel.NONE, PermissionLevel.READ_ONLY):
            return "allow", ""
        return "deny", "plan mode only allows read-only tools"

    if level in (PermissionLevel.NONE, PermissionLevel.READ_ONLY):
        return "allow", ""

    return "ask", format_permission_reason(tool_name, input_dict, level)


def remember_persistent_rule(action: Literal["allow", "deny"], rule: str) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    perms = data.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
        data["permissions"] = perms
    bucket = perms.get(action)
    if not isinstance(bucket, list):
        bucket = []
        perms[action] = bucket
    if rule not in bucket:
        bucket.append(rule)
    SETTINGS_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


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
