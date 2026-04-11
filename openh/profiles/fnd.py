"""Fruits & Dessert (FnD) profile — ESP32 / nRF52840 / Pi5 / RTL8812BU session."""
from __future__ import annotations

import re
from pathlib import Path

from . import ProfileSpec, register

WIFI_REPO = Path.home() / "Projects" / "wifi" / "wifi-hack-demo"


def _read_file(path: Path, max_lines: int = 0) -> str:
    """Read file content, return empty string on any error."""
    try:
        text = path.read_text(encoding="utf-8")
        if max_lines > 0:
            text = "\n".join(text.splitlines()[:max_lines])
        return text.strip()
    except Exception:
        return ""


def _extract_section(text: str, heading: str, *, max_lines: int = 40) -> str:
    """Extract a markdown section by heading (## or ###), limited to max_lines."""
    pattern = rf"(?:^|\n)(#{1,3}\s+{re.escape(heading)}.*?)(?=\n#{1,3}\s|\Z)"
    m = re.search(pattern, text, re.DOTALL)
    if not m:
        return ""
    lines = m.group(1).strip().splitlines()[:max_lines]
    return "\n".join(lines)


def _abbreviate_commands(text: str) -> str:
    """Extract command names + one-line descriptions from a MANUAL-style doc.

    Looks for patterns like:
      ## command_name
      description text
    or table rows like:
      | command | description |
    """
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Markdown heading commands (## cmd or ### cmd)
        if re.match(r"^#{2,3}\s+\w", line):
            cmd = re.sub(r"^#{2,3}\s+", "", line).strip()
            desc = ""
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line and not next_line.startswith("#"):
                    desc = next_line[:100]
            out.append(f"  {cmd}: {desc}" if desc else f"  {cmd}")
        # Table rows
        elif "|" in line and not line.startswith("|--") and not line.startswith("| -"):
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) >= 2 and not cells[0].lower().startswith("command"):
                out.append(f"  {cells[0]}: {cells[1][:100]}")
        i += 1
    return "\n".join(out[:50])  # cap at 50 entries


def _extract_command_table(text: str) -> str:
    """Extract markdown table from text (for WIFI_RESEARCH command ref)."""
    lines = text.splitlines()
    table_lines: list[str] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and "|" in stripped[1:]:
            in_table = True
            table_lines.append(stripped)
        elif in_table:
            break
    return "\n".join(table_lines[:40])


def _build_fnd_system_prompt() -> str:
    """Build the FnD system prompt by reading reference files at runtime."""
    sections: list[str] = []

    # 1. CLAUDE.md content (project instructions)
    claude_md = _read_file(WIFI_REPO / "CLAUDE.md", max_lines=80)
    if claude_md:
        sections.append(f"# Project Instructions (CLAUDE.md)\n{claude_md}")

    # 2. Infrastructure summary
    sections.append("""# Infrastructure
Devices:
  - ESP32-S3 "hci_research" — Bluetooth HCI research firmware (USB-serial)
  - ESP32-S3 "wifi_research" — WiFi monitor/inject firmware (USB-serial)
  - nRF52840 Dongle v1.0 — BLE sniffer/injector (CDC ACM)
  - Raspberry Pi 5 — headless Linux host (Tailscale)
  - RTL8812BU USB adapter — 802.11ac monitor mode on Pi5

Serial ports (macOS):
  - /dev/tty.usbserial-* — ESP32 devices
  - /dev/tty.usbmodem* — nRF52840 CDC ACM

Tailscale IPs:
  - Pi5: see tailscale status for current IP
  - Mac: local""")

    # 3. ESP32 hci_research command reference (abbreviated from MANUAL.md)
    manual = _read_file(WIFI_REPO / "MANUAL.md")
    if manual:
        cmds = _abbreviate_commands(manual)
        if cmds:
            sections.append(f"# ESP32 hci_research Commands\n{cmds}")

    # 4. ESP32 wifi_research command reference
    wifi_doc = _read_file(WIFI_REPO / "docs" / "ops" / "WIFI_RESEARCH.md")
    if wifi_doc:
        table = _extract_command_table(wifi_doc)
        if table:
            sections.append(f"# ESP32 wifi_research Commands\n{table}")

    # 5. nRF52840 command reference (help output)
    nrf_help = _read_file(WIFI_REPO / "docs" / "ops" / "NRF_HELP.md", max_lines=50)
    if nrf_help:
        sections.append(f"# nRF52840 v1.0 Commands\n{nrf_help}")

    # 6. Serial port mapping
    sections.append("""# Serial Port Rules
- nRF52840 CDC (port contains "usbmodem"): use slow write — 30ms delay per char
- ESP32 (port contains "usbserial"): normal write speed
- Always wait for prompt/response before sending next command
- Default baud: 115200 for ESP32, CDC speed irrelevant for nRF""")

    # 7. Critical rules
    sections.append("""# Critical Rules
- NEVER run erase_flash on any ESP32 — destroys PHY calibration data
- PHY calibration: factory-burned, irreplaceable; if lost, device is bricked for RF
- Pi5 wlan0: do NOT manage wlan0 — it is the Tailscale uplink; only use wlan1 (RTL8812BU)
- Always confirm device identity before sending commands
- After flashing, wait for reboot + prompt before interacting""")

    # 8. STYLE.md essence (abbreviated)
    style_md = _read_file(WIFI_REPO / "STYLE.md", max_lines=60)
    if style_md:
        sections.append(f"# Writing Style\n{style_md}")
    else:
        sections.append("""# Writing Style
- 1st person observer tone ("~했다", "~인 것 같다")
- Forbidden words: 확인 → 살펴보다/점검; 진행 → 수행/실행; 활용 → 사용/쓰다; 통해 → ~(으)로/~해서
- No honorifics in technical logs; use 해체 (plain form)
- Be concise; no filler phrases""")

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
#  Register
# ---------------------------------------------------------------------------

register(ProfileSpec(
    id="fnd",
    display_name="Fruits & Dessert",
    wordmark="Fruits & Dessert",
    icon="\U0001f353",
    default_cwd=str(WIFI_REPO),
    system_prompt_fn=_build_fnd_system_prompt,
    extra_tools_fn=lambda: __import__("openh.tools", fromlist=["fnd_extra_tools"]).fnd_extra_tools(),
    accent_color="#d4a857",
    color_preset="Fruits & Dessert",
    placeholder="\uc5b4\ub5a4 \uc7a5\ube44\ub97c \uad00\ucc30\ud560\uae4c\uc694?",
    subtitle="ESP32 \u00b7 nRF52840 \u00b7 Pi5 \u00b7 RTL8812BU",
))
