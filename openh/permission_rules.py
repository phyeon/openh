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
from .coordinator import COORDINATOR_BANNED_TOOLS, is_coordinator_mode
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


@dataclass(frozen=True)
class PermissionRequest:
    tool_name: str
    input_dict: dict[str, Any]
    level: PermissionLevel
    is_read_only: bool


class PermissionHandler:
    def check_permission(self, request: PermissionRequest) -> tuple[Decision, str]:
        raise NotImplementedError

    def request_permission(self, request: PermissionRequest) -> tuple[Decision, str]:
        return self.check_permission(request)


class AutoPermissionHandler(PermissionHandler):
    def __init__(self, mode: PermissionMode) -> None:
        self.mode = mode

    def check_permission(self, request: PermissionRequest) -> tuple[Decision, str]:
        if self.mode == PermissionMode.BYPASS_PERMISSIONS:
            return "allow", ""
        if self.mode == PermissionMode.ACCEPT_EDITS:
            return "allow", ""
        if request.level == PermissionLevel.FORBIDDEN:
            return "deny", "this action is unconditionally forbidden"
        if self.mode == PermissionMode.PLAN:
            if request.is_read_only:
                return "allow", ""
            return "deny", "plan mode only allows read-only tools"
        if request.is_read_only:
            return "allow", ""
        return "deny", format_permission_reason(
            request.tool_name,
            request.input_dict,
            request.level,
        )


class InteractivePermissionHandler(PermissionHandler):
    def __init__(self, mode: PermissionMode) -> None:
        self.mode = mode

    def check_permission(self, request: PermissionRequest) -> tuple[Decision, str]:
        if self.mode == PermissionMode.BYPASS_PERMISSIONS:
            return "allow", ""
        if request.level == PermissionLevel.FORBIDDEN:
            return "deny", "this action is unconditionally forbidden"
        if self.mode == PermissionMode.PLAN:
            if request.is_read_only:
                return "allow", ""
            return "deny", "plan mode only allows read-only tools"
        return "allow", ""


class PermissionManager:
    def __init__(self, session: Any, rules: PermissionRules) -> None:
        self.session = session
        self.rules = rules

    def _coordinator_ban(self, request: PermissionRequest) -> tuple[Decision, str]:
        if not is_coordinator_mode():
            return "none", ""
        if bool(getattr(self.session, "is_non_interactive", False)):
            return "none", ""
        if request.tool_name not in COORDINATOR_BANNED_TOOLS:
            return "none", ""
        return (
            "deny",
            f"{request.tool_name} is disabled in coordinator mode; delegate this to a worker agent instead.",
        )

    def _evaluate_rules(self, request: PermissionRequest) -> tuple[Decision, str]:
        deny_patterns = list(self.rules.deny)
        allow_patterns = list(self.rules.allow)
        ask_patterns = list(self.rules.ask)

        always_deny = getattr(self.session, "always_deny", set())
        if isinstance(always_deny, set):
            for tool_name, pattern in always_deny:
                deny_patterns.append(
                    tool_name if pattern == "*" else f"{tool_name}({pattern})"
                )

        always_allow = getattr(self.session, "always_allow", set())
        if isinstance(always_allow, set):
            for tool_name, pattern in always_allow:
                allow_patterns.append(
                    tool_name if pattern == "*" else f"{tool_name}({pattern})"
                )

        deny_matched = any(
            _match_rule(pattern, request.tool_name, request.input_dict)
            for pattern in deny_patterns
        )
        if deny_matched:
            return "deny", "permission denied by rule"

        allow_matched = any(
            _match_rule(pattern, request.tool_name, request.input_dict)
            for pattern in allow_patterns
        )
        if allow_matched:
            return "allow", ""

        ask_matched = any(
            _match_rule(pattern, request.tool_name, request.input_dict)
            for pattern in ask_patterns
        )
        if ask_matched:
            return "ask", format_permission_reason(
                request.tool_name,
                request.input_dict,
                request.level,
            )

        return "none", ""

    def _default_decision(
        self,
        request: PermissionRequest,
        *,
        interactive: bool,
    ) -> tuple[Decision, str]:
        mode = effective_permission_mode(self.session)
        if mode == PermissionMode.BYPASS_PERMISSIONS:
            return "allow", ""
        if mode == PermissionMode.ACCEPT_EDITS:
            return "allow", ""
        if mode == PermissionMode.PLAN:
            if request.is_read_only:
                return "allow", ""
            return "deny", "plan mode only allows read-only tools"
        if request.is_read_only:
            return "allow", ""

        reason = format_permission_reason(
            request.tool_name,
            request.input_dict,
            request.level,
        )
        if interactive:
            return "ask", reason
        return "deny", reason

    def evaluate(
        self,
        request: PermissionRequest,
        *,
        interactive: bool,
    ) -> tuple[Decision, str]:
        if request.level == PermissionLevel.FORBIDDEN:
            return "deny", "this action is unconditionally forbidden"
        coordinator_decision, coordinator_reason = self._coordinator_ban(request)
        if coordinator_decision != "none":
            return coordinator_decision, coordinator_reason
        rule_decision, reason = self._evaluate_rules(request)
        if rule_decision != "none":
            if rule_decision == "ask" and not interactive:
                return "deny", reason
            return rule_decision, reason
        default_decision, default_reason = self._default_decision(
            request,
            interactive=interactive,
        )
        if default_decision == "ask" and not interactive:
            return "deny", default_reason
        return default_decision, default_reason


class ManagedAutoPermissionHandler(PermissionHandler):
    def __init__(self, manager: PermissionManager) -> None:
        self.manager = manager

    def check_permission(self, request: PermissionRequest) -> tuple[Decision, str]:
        return self.manager.evaluate(request, interactive=False)


class ManagedInteractivePermissionHandler(PermissionHandler):
    def __init__(self, manager: PermissionManager) -> None:
        self.manager = manager

    def check_permission(self, request: PermissionRequest) -> tuple[Decision, str]:
        return self.manager.evaluate(request, interactive=True)


def interactive_with_manager(manager: PermissionManager) -> ManagedInteractivePermissionHandler:
    return ManagedInteractivePermissionHandler(manager)


def auto_with_manager(manager: PermissionManager) -> ManagedAutoPermissionHandler:
    return ManagedAutoPermissionHandler(manager)


def effective_permission_mode(session: Any) -> PermissionMode:
    if bool(getattr(session, "plan_mode", False)):
        return PermissionMode.PLAN
    raw = str(getattr(session, "permission_mode", "") or "").strip().lower()
    for mode in PermissionMode:
        if raw == mode.value:
            return mode
    return PermissionMode.DEFAULT


def build_permission_handler(
    session: Any,
    rules: PermissionRules,
) -> PermissionHandler:
    forced_non_interactive = bool(getattr(session, "is_non_interactive", False))
    kind = str(
        getattr(
            session,
            "permission_handler_kind",
            "auto" if forced_non_interactive else "interactive",
        )
        or ("auto" if forced_non_interactive else "interactive")
    ).strip().lower()
    if forced_non_interactive and kind == "interactive":
        kind = "auto"
    manager = PermissionManager(session, rules)
    if kind.strip().lower() == "auto":
        return ManagedAutoPermissionHandler(manager)
    return ManagedInteractivePermissionHandler(manager)


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
    if tool_name in ("Glob", "Grep"):
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
        return f"Bash wants to run: `{command}`\nThis will execute a shell command."
    if level == PermissionLevel.WRITE:
        target = str(
            input_dict.get("file_path")
            or input_dict.get("notebook_path")
            or input_dict.get("path")
            or input_dict.get("name")
            or tool_name
        ).strip()
        extra = "\nThis will write to the filesystem."
        lowered = target.replace("\\", "/")
        if "/etc/" in lowered:
            extra = (
                "\nModifying system files could affect network resolution and system configuration."
            )
        elif target.startswith("~/.") or "/." in lowered:
            extra = "\nThis is a hidden/configuration file."
        return f"{tool_name} wants to write to `{target}`{extra}"
    if level == PermissionLevel.DANGEROUS:
        target = str(input_dict.get("command") or input_dict.get("path") or tool_name).strip()
        return (
            f"{tool_name} wants dangerous access: `{target}`\n"
            "This may affect the system outside the workspace."
        )
    if tool_name == "WebFetch":
        target = str(input_dict.get("url") or "").strip() or tool_name
        return (
            f"WebFetch wants to fetch: `{target}`\n"
            "This will make an outbound HTTP request."
        )
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
    request = PermissionRequest(
        tool_name=tool_name,
        input_dict=input_dict,
        level=level,
        is_read_only=level in (PermissionLevel.NONE, PermissionLevel.READ_ONLY),
    )
    handler = build_permission_handler(session, rules)
    return handler.request_permission(request)


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
    if tool_name in ("Glob", "Grep"):
        path = (input_dict.get("path") or input_dict.get("pattern") or "")
        return fnmatch.fnmatchcase(path, rule_pattern)
    if tool_name in ("WebFetch", "WebSearch"):
        value = (input_dict.get("url") or input_dict.get("query") or "")
        return fnmatch.fnmatchcase(value, rule_pattern)
    return False
