"""Minimal MCP (Model Context Protocol) stdio client.

Spawns an MCP server as a subprocess, exchanges JSON-RPC messages over stdio,
and exposes its tools to the agent as regular Tool instances.

Configuration lives in ~/.openh/mcp.json:

{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/hyeon"],
      "env": {}
    },
    ...
  }
}

Tools from MCP servers are wrapped as McpTool(Tool) instances with names
prefixed by the server name (e.g. "filesystem.read_file").
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tools.base import PermissionDecision, Tool, ToolContext

CONFIG_PATH = Path.home() / ".openh" / "mcp.json"


@dataclass
class McpServer:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    process: asyncio.subprocess.Process | None = None
    _next_id: int = 1
    _tools: list[dict[str, Any]] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def start(self) -> None:
        if self.process is not None:
            return
        full_env = os.environ.copy()
        full_env.update(self.env or {})
        self.process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=full_env,
        )

        # initialize
        await self._send({
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "openh", "version": "0.1.0"},
            },
        })
        self._next_id += 1
        await self._recv()
        await self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # list tools
        await self._send({
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": "tools/list",
        })
        self._next_id += 1
        resp = await self._recv()
        tools_list = (resp.get("result") or {}).get("tools") or []
        self._tools = tools_list

    async def _send(self, payload: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError(f"MCP server {self.name} not started")
        line = (json.dumps(payload) + "\n").encode("utf-8")
        self.process.stdin.write(line)
        await self.process.stdin.drain()

    async def _recv(self) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise RuntimeError(f"MCP server {self.name} not started")
        while True:
            raw = await self.process.stdout.readline()
            if not raw:
                raise RuntimeError(f"MCP server {self.name} closed stdout")
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                continue

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        async with self._lock:
            await self._send({
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            })
            self._next_id += 1
            resp = await self._recv()

        result = resp.get("result") or {}
        if "error" in resp:
            return f"error: {resp['error'].get('message', 'mcp error')}"
        content = result.get("content") or []
        out_parts: list[str] = []
        for c in content:
            if c.get("type") == "text":
                out_parts.append(c.get("text", ""))
        return "\n".join(out_parts) if out_parts else json.dumps(result)

    def tools_metadata(self) -> list[dict[str, Any]]:
        return self._tools

    async def stop(self) -> None:
        if self.process is not None:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=3)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass


class McpTool(Tool):
    def __init__(self, server: McpServer, meta: dict[str, Any]) -> None:
        self._server = server
        self._meta = meta
        tool_name = meta.get("name", "")
        prefixed = f"{server.name}.{tool_name}"
        # These have to be set as instance attributes, overriding ClassVars.
        self.name = prefixed  # type: ignore[misc]
        self.description = meta.get("description", "MCP tool") or "MCP tool"  # type: ignore[misc]
        schema = meta.get("inputSchema") or {"type": "object", "properties": {}}
        self.input_schema = schema  # type: ignore[misc]
        self._underlying_name = tool_name

    async def check_permissions(
        self, input: dict[str, Any], ctx: ToolContext
    ) -> PermissionDecision:
        return PermissionDecision(behavior="ask")

    async def run(self, input: dict[str, Any], ctx: ToolContext) -> str:
        try:
            return await self._server.call_tool(self._underlying_name, input or {})
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"


def load_mcp_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"servers": {}}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"servers": {}}


async def build_mcp_tools() -> list[Tool]:
    """Load MCP config, start servers, return wrapped tools."""
    cfg = load_mcp_config()
    servers_cfg = (cfg.get("servers") or {})
    tools: list[Tool] = []
    for name, spec in servers_cfg.items():
        try:
            srv = McpServer(
                name=name,
                command=spec.get("command", ""),
                args=list(spec.get("args") or []),
                env=dict(spec.get("env") or {}),
            )
            await srv.start()
            for meta in srv.tools_metadata():
                tools.append(McpTool(srv, meta))
        except Exception:
            continue
    return tools
