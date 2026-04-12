"""Serial port tool — send commands to BLE/WiFi hardware via serial."""
from __future__ import annotations

import asyncio
import time
from typing import Any, ClassVar

from .base import PermissionDecision, PermissionLevel, Tool, ToolContext

# Connection pool: port_path -> (serial.Serial, last_used_timestamp)
_connection_pool: dict[str, tuple[Any, float]] = {}


def _get_connection(port: str, timeout: float = 10.0) -> Any:
    """Get or create a serial connection, reusing from pool if available."""
    import serial  # pyserial

    now = time.time()
    if port in _connection_pool:
        conn, _last = _connection_pool[port]
        if conn.is_open:
            _connection_pool[port] = (conn, now)
            return conn
        # Connection was closed, remove from pool
        try:
            conn.close()
        except Exception:
            pass
        del _connection_pool[port]

    # Determine baud rate (ESP32 = 115200, nRF CDC = irrelevant but set 115200)
    baud = 115200
    conn = serial.Serial(port, baudrate=baud, timeout=timeout)
    _connection_pool[port] = (conn, now)
    return conn


def _is_nrf_cdc(port: str) -> bool:
    """Check if port is an nRF52840 CDC device (needs slow write)."""
    return "usbmodem" in port.lower()


def _is_esp32(port: str) -> bool:
    """Check if port is an ESP32 device."""
    return "usbserial" in port.lower()


class SerialTool(Tool):
    name: ClassVar[str] = "Serial"
    permission_level = PermissionLevel.DANGEROUS
    description: ClassVar[str] = (
        "Send a command to a serial device (ESP32, nRF52840) and capture the response. "
        "Auto-detects nRF CDC ports (slow write) vs ESP32 (normal write). "
        "Connections are reused within the session."
    )
    input_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "port": {
                "type": "string",
                "description": "Serial port path, e.g. /dev/tty.usbserial-110 or /dev/tty.usbmodem14201",
            },
            "command": {
                "type": "string",
                "description": "Command string to send (newline appended automatically)",
            },
            "wait": {
                "type": "number",
                "description": "Seconds to wait for response after sending (default 2)",
                "default": 2,
            },
            "timeout": {
                "type": "number",
                "description": "Serial read timeout in seconds (default 10)",
                "default": 10,
            },
        },
        "required": ["port", "command"],
    }
    is_read_only: ClassVar[bool] = False
    is_destructive: ClassVar[bool] = False

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        # Always ask — hardware interaction
        port = input.get("port", "")
        cmd = input.get("command", "")
        return PermissionDecision(
            behavior="ask",
            reason=f"Send '{cmd}' to {port}",
        )

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        port = input.get("port", "")
        command = input.get("command", "")
        wait_secs = float(input.get("wait", 2))
        timeout_secs = float(input.get("timeout", 10))

        if not port:
            return "Error: port is required"
        if not command:
            return "Error: command is required"

        try:
            return await asyncio.get_event_loop().run_in_executor(
                None,
                self._run_sync,
                port,
                command,
                wait_secs,
                timeout_secs,
            )
        except Exception as exc:
            return f"Serial error: {exc}"

    def _run_sync(
        self, port: str, command: str, wait_secs: float, timeout_secs: float
    ) -> str:
        conn = _get_connection(port, timeout=timeout_secs)

        # Flush any pending input
        conn.reset_input_buffer()

        # Send command
        cmd_bytes = (command + "\n").encode("utf-8")
        if _is_nrf_cdc(port):
            # Slow write for nRF CDC: 30ms per character
            for byte in cmd_bytes:
                conn.write(bytes([byte]))
                time.sleep(0.03)
        else:
            conn.write(cmd_bytes)

        # Wait for device to process
        time.sleep(wait_secs)

        # Read all available output
        output_chunks: list[bytes] = []
        deadline = time.time() + timeout_secs
        while time.time() < deadline:
            waiting = conn.in_waiting
            if waiting > 0:
                output_chunks.append(conn.read(waiting))
                time.sleep(0.1)  # brief pause to accumulate more
            else:
                if output_chunks:
                    # Got some data and nothing more is coming
                    break
                time.sleep(0.1)

        if not output_chunks:
            return "(no response within timeout)"

        raw = b"".join(output_chunks)
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            text = repr(raw)

        # Strip the echoed command if present
        lines = text.splitlines()
        if lines and command.strip() in lines[0]:
            lines = lines[1:]

        return "\n".join(lines).strip() or "(empty response)"
