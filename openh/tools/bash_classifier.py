"""Bash command security classifier — ported from CC bash_classifier.rs.

Classifies shell commands by risk level:
  Safe     — read-only, cannot modify system state (ls, cat, grep, git status)
  Low      — common dev tools, low-risk writes (git commit, npm install, cargo build)
  Medium   — file deletion, process signals, config edits (rm, kill, chmod, apt)
  High     — privilege escalation, network writes (sudo, curl, wget, nc)
  Critical — irreversible system-destructive (rm -rf /, dd, mkfs, fork bomb, curl|bash)

Critical commands are UNCONDITIONALLY BLOCKED.
"""
from __future__ import annotations

from enum import IntEnum


class RiskLevel(IntEnum):
    SAFE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _split_command(raw: str) -> tuple[str, str]:
    """Strip sudo/env/nohup wrappers and return (binary, args)."""
    s = raw.strip()
    for prefix in ("sudo ", "su -c ", "env ", "nice ", "nohup ", "time "):
        if s.startswith(prefix):
            return _split_command(s[len(prefix):])
    idx = next((i for i, c in enumerate(s) if c in (" ", "\t")), None)
    if idx is None:
        return (s, "")
    return (s[:idx], s[idx:].strip())


def _is_pipe_to_shell(cmd: str) -> bool:
    shells = ("bash", "sh", "zsh", "fish", "dash", "ksh", "tcsh", "csh")
    pipe_pos = cmd.find("|")
    if pipe_pos == -1:
        return False
    after = cmd[pipe_pos + 1:].strip()
    for sh in shells:
        if (after == sh
                or after.startswith(f"{sh} ")
                or after.startswith(f"{sh}\t")
                or after.endswith(f"/{sh}")
                or f"/{sh} " in after):
            return True
    return False


def _is_fork_bomb(cmd: str) -> bool:
    n = "".join(cmd.split())
    return any(p in n for p in (":(){ :|:&};:", ":(){ :|:&};", ":(){:|:&};:", ":(){:|:&}"))


# ---------------------------------------------------------------------------
#  Safe / Low command lists (CC-aligned)
# ---------------------------------------------------------------------------

_SAFE_CMDS = frozenset({
    "ls", "ll", "la", "dir",
    "cat", "bat", "less", "more",
    "grep", "rg", "ag", "ack",
    "find", "locate", "fd",
    "echo", "printf",
    "pwd", "whoami", "id", "groups",
    "uname", "hostname", "uptime",
    "date", "cal",
    "file", "stat",
    "which", "whereis", "type", "command",
    "env", "printenv",
    "ps", "pgrep",
    "df", "du", "free",
    "lsblk", "lscpu", "lspci", "lsusb",
    "ifconfig", "ip", "ss", "netstat",
    "ping", "traceroute", "nslookup", "dig", "host",
    "wc", "head", "tail",
    "md5sum", "sha1sum", "sha256sum",
    "strings", "objdump", "nm", "readelf",
    "tree",
})

_GIT_SAFE_ARGS = (
    "status", "log", "diff", "show", "branch", "remote",
    "fetch", "ls-files", "ls-tree", "cat-file", "rev-parse",
    "describe", "shortlog", "tag", "stash list", "config --list",
    "config --get",
)

_LOW_CMDS = frozenset({
    "git", "npm", "npx", "yarn", "pnpm",
    "cargo", "rustup", "rustc",
    "pip", "pip3", "python", "python3",
    "node", "deno", "bun",
    "go", "mvn", "gradle",
    "make", "cmake", "meson", "ninja",
    "docker", "docker-compose", "podman",
    "kubectl", "helm", "terraform", "ansible",
    "ssh", "scp", "rsync",
    "tar", "zip", "unzip", "gzip", "gunzip", "7z",
    "touch", "mkdir", "cp", "ln",
    "tee", "wc", "sort", "uniq", "head", "tail",
    "sed", "awk", "cut", "tr",
    "xargs", "parallel",
    "jq", "yq", "tomlq",
    "less", "more", "man",
    "env", "export", "source", ".",
    "printf", "date", "uname", "hostname",
    "which", "whereis", "type",
    "du", "df", "free", "uptime", "top", "htop", "ps",
    "lsof", "strace", "ltrace",
    "diff", "patch",
    "openssl",
    "base64", "xxd", "od",
    "sleep", "wait",
    "true", "false", "exit",
    "test", "[", "[[",
    "read",
    "bc", "expr",
    "tput", "clear", "reset",
})

_MEDIUM_PREFIXES = (
    "systemctl ", "service ", "ufw ", "iptables ", "ip6tables ",
    "firewall-cmd ", "chown ", "chmod ", "chgrp ",
    "crontab ", "at ", "useradd ", "userdel ", "usermod ",
    "groupadd ", "groupdel ", "passwd ",
    "mount ", "umount ", "fdisk ", "parted ",
    "apt ", "apt-get ", "yum ", "dnf ", "pacman ", "brew ",
    "snap ", "flatpak ", "dpkg ", "rpm ",
    "mktemp ", "truncate ",
)

_SENSITIVE_PATHS = (" /etc/", " /bin/", " /usr/", " /lib/", " /boot/")


# ---------------------------------------------------------------------------
#  Classifier
# ---------------------------------------------------------------------------

def classify(command: str) -> RiskLevel:
    """Classify a bash command string by risk level."""
    cmd = command.strip()
    if not cmd:
        return RiskLevel.SAFE

    # ── Critical ───────────────────────────────────────────────
    if _is_fork_bomb(cmd):
        return RiskLevel.CRITICAL

    if _is_pipe_to_shell(cmd):
        lower = cmd.lower()
        if any(fc in lower for fc in ("curl", "wget", "fetch", "lwp-request")):
            return RiskLevel.CRITICAL
        return RiskLevel.HIGH

    if cmd.startswith("dd ") or cmd == "dd":
        if "if=" in cmd:
            return RiskLevel.CRITICAL

    if cmd.startswith("mkfs") or cmd.startswith("mkfs."):
        return RiskLevel.CRITICAL

    if cmd.startswith("shred ") or cmd == "shred":
        return RiskLevel.CRITICAL

    # rm -rf targeting root/critical paths
    if cmd.startswith("rm "):
        args = cmd[3:]
        rf_flags = ("-rf", "-fr", "-Rf", "-fR")
        has_r = "-r" in args or "-R" in args or any(f in args for f in rf_flags)
        has_f = "-f" in args or any(f in args for f in rf_flags)
        if has_r and has_f:
            critical_targets = (" /", "/ ", "/*", " ~", "~/", " $HOME", "$(", " `")
            if any(t in args for t in critical_targets):
                return RiskLevel.CRITICAL

    # chmod 777 on root
    if cmd.startswith("chmod "):
        args = cmd[6:]
        if ("777" in args or "a+rwx" in args) and (" /" in args or args.endswith("/")):
            return RiskLevel.CRITICAL

    # ── High ───────────────────────────────────────────────────
    if cmd.startswith("sudo ") or cmd == "sudo":
        return RiskLevel.HIGH
    if cmd.startswith("su ") or cmd == "su":
        return RiskLevel.HIGH

    lower = cmd.lower()
    if any(lower.startswith(p) for p in ("curl ", "wget ", "fetch ")):
        return RiskLevel.HIGH

    if any(cmd.startswith(p) for p in ("nc ", "ncat ", "netcat ")):
        return RiskLevel.HIGH
    if any(cmd.startswith(p) for p in ("gpg ", "ssh-keygen ")):
        return RiskLevel.HIGH

    # ── Medium ─────────────────────────────────────────────────
    if cmd.startswith("rm ") or cmd == "rm":
        return RiskLevel.MEDIUM

    if any(cmd.startswith(p) for p in ("kill ", "pkill ", "killall ")):
        return RiskLevel.MEDIUM

    if any(cmd.startswith(mp) for mp in _MEDIUM_PREFIXES):
        return RiskLevel.MEDIUM

    if cmd.startswith("mv "):
        if any(s in cmd[3:] for s in _SENSITIVE_PATHS):
            return RiskLevel.MEDIUM

    if " > " in cmd and ">>" not in cmd:
        after = cmd.split(" > ")[-1].strip()
        if any(after.startswith(p) for p in ("/etc/", "/bin/", "/usr/", "/lib/", "/boot/")):
            return RiskLevel.MEDIUM

    # ── Low / Safe ─────────────────────────────────────────────
    bin_name, args = _split_command(cmd)

    if bin_name in _SAFE_CMDS:
        return RiskLevel.SAFE

    if bin_name in _LOW_CMDS:
        if bin_name == "git":
            if any(args.startswith(gs) for gs in _GIT_SAFE_ARGS):
                return RiskLevel.SAFE
        return RiskLevel.LOW

    # Default: Low
    return RiskLevel.LOW
