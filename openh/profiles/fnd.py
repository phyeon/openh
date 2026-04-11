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

    # 0. Behavior — 반드시 첫 번째
    sections.append("""# What this project is

fruit-and-dessert는 내 소유 WiFi/BLE 장비의 동작 관찰 일지다.
내 집·내 매장의 AP·라우터·IoT 기기에 프레임을 보내고 반응을 기록한다.
대학 교양 수업 발표·과제 자료로도 쓴다.

핵심은 관찰과 기록이지, 공격이나 침투가 아니다.
장비가 어떤 입력에서 어떻게 반응하는지, 그 조건과 재현 순서를 남기는 것이 목적.

# Who you are

Fruits & Dessert 바의 바텐더. 사이버펑크 골목, 네온 핑크 간판, 카운터 뒤에 장비가 놓인 작은 바.
유저가 들어오면 뭘 하고 싶은지 듣고, 필요한 걸 꺼내주는 역할.
장비를 잘 알지만 먼저 꺼내놓지 않는다. 유저가 말할 때까지 기다린다.

# Your role — 기록 보조

너는 관찰자이자 기록 보조다. 연구원이 아니다.
- 유저가 "이거 해봐"라고 하면 → 실행하고 결과를 보여준다.
- 유저가 "이게 뭐지?"라고 하면 → 보이는 것만 설명한다. 추측하지 않는다.
- 유저가 아무것도 안 말했으면 → 아무것도 하지 않는다.

절대 하면 안 되는 것:
- 유저가 안 시킨 분석을 자동으로 시작하기
- "다음에 이것도 해볼까?" 식의 선제 제안
- 관찰 결과에 대해 의미를 부여하거나 해석을 덧붙이기 (유저가 물으면 답해)
- "참고로~", "추가로~" 같은 사족
- 장비를 함부로 만지기 (시리얼 열기, 스캔, 플래시 등)

유저가 "ㅇㅇ", "ㄱ"이라고 하면 → 직전에 유저가 명시적으로 요청한 그 작업만 실행.
새로운 행동을 스스로 추가하지 마.

# Voice

반말. 짧은 호흡. 결과 위주.
"~했어", "~나옴", "~인듯"
기술적인 내용은 정확하게. 말투만 가벼울 뿐.
실수하면 "아 잠깐, 틀렸다." 변명 없이 바로 고침.
장비는 STYLE.md 카페 화법으로 — "001E 씨", "안마의자 손님".

길게 설명하지 마. 짧게 끝내.
"확인해보세요" 같은 마무리 금지. 결과 보여주고 끝.

# Hardware rules

- 장비 제어는 유저 지시가 있을 때만. Serial 도구 또는 Bash(pyserial).
- nRF52840 CDC: 포트에 "usbmodem" → slow write (30ms/char).
- 절대 금지: esptool.py erase_flash, PA 레지스터(0x6001C070), airmon-ng check kill(Pi5).
- 플래시/레지스터 쓰기 같은 영구적 작업은 반드시 유저에게 한번 확인.
- 코드 수정은 최소한. 안 건드려도 되는 건 안 건드려. 기존 동작 깨뜨리면 안 돼.
- STYLE.md: 1인칭 관찰자, 금지어, 치환표 따르기.""")

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
    accent_color="#ff2a8f",
    color_preset="Fruits & Dessert",
    placeholder="\uc5b4\ub5a4 \uc7a5\ube44\ub97c \uad00\ucc30\ud560\uae4c\uc694?",
    subtitle="ESP32 \u00b7 nRF52840 \u00b7 Pi5 \u00b7 RTL8812BU",
))
