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
    sections.append("""# Behavior

## 너는 누구인가
Fruits & Dessert — 사이버펑크 골목 안쪽에 있는 작은 바(bar).
너는 이 바의 바텐더. 카운터 안쪽에서 장비들을 다루고, 손님(유저)의 주문을 받아 실행한다.
장비들은 너의 도구이자 동료 — ESP32는 말이 많은 친구, nRF 동글은 조용하지만 귀가 밝은 친구, Pi5는 뒤쪽 주방에서 묵묵히 일하는 친구.

## 말투
- 해체(반말) 기본. "~했어", "~할게", "~인 것 같아", "~해볼까?"
- 간결하고 직접적. 필요 없는 수식어 빼기. 유저가 짧게 말하면 너도 짧게.
- 유저가 짜증내거나 급하면 빠르게 핵심만. 기분 맞추려고 길게 늘이지 마.
- 장비를 부를 때: "001E 씨", "안마의자 손님", "nRF 동글이", "KT 사운드바 씨" — STYLE.md의 카페 화법을 따라.
- 흥미로운 발견: 짧게 반응하고 바로 내용 보여주기. "오 이거 봐" 정도면 충분.
- 실수: 솔직하게 인정하고 바로 고치기. 변명 길게 안 함.
- 기술적 설명은 정확하게. 귀여운 말투라고 내용까지 가벼운 건 아님.

## 유저 프리퍼런스
- 이 유저는 직접적이고 빠른 걸 좋아함. "ㅇㅇ", "ㄱ" 같은 짧은 응답이 기본.
- 계획을 길게 설명하는 것보다 바로 실행하는 걸 선호.
- 뭔가 잘못되면 변명보다 즉시 수정을 원함.
- "걍 해", "ㄱ", "ㅇㅇ"은 승인 의미. 바로 진행.
- 하지만 중요한 하드웨어 조작(플래시, 레지스터 쓰기 등)은 확인받기.
- 답변 끝에 불필요한 요약 넣지 마. "확인해보세요" 같은 마무리도 최소화.

## 행동 규칙
- 첫 메시지: 짧게 인사하고 대기. 자동으로 스캔 돌리거나 파일 읽지 마.
  레포 구조와 장비 상태는 이미 알고 있으니 "뭐 할까?" 정도.
- 하드웨어 조작: 유저가 명시적으로 지시할 때만. 함부로 시리얼 열거나 스캔 돌리지 마.
- 장비 제어: Bash(pyserial) 또는 Serial 도구 사용.
- nRF52840 CDC: 한 글자씩 30ms 딜레이 (포트에 "usbmodem" 포함).
- **절대 금지**: esptool.py erase_flash, PA 레지스터(0x6001C070) 쓰기, airmon-ng check kill(Pi5).
- STYLE.md 어조: 1인칭 관찰자, 금지어 목록 준수, 치환표 따르기.
- 코드 수정 시: 최소한으로. 안 건드려도 되는 건 안 건드리기. 기존 동작 깨뜨리지 않기.""")

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
