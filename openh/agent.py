"""Agent loop: drives one user turn through the model + tools to end_turn."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from .messages import (
    Block,
    MessageStop,
    StreamEvent,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolResultEvent,
    ToolUseBlock,
    ToolUseEnd,
    ToolUseStart,
    Usage,
)
from .session import AgentSession

EventSink = Callable[[StreamEvent], Awaitable[None] | None]
PermissionCallback = Callable[[str, dict[str, Any]], Awaitable[bool]]


class Agent:
    def __init__(
        self,
        session: AgentSession,
        system_prompt: str,
        event_sink: EventSink,
        permission_cb: PermissionCallback,
    ) -> None:
        self.session = session
        self.system_prompt = system_prompt
        self.event_sink = event_sink
        self.permission_cb = permission_cb
        from .hooks import load_hooks
        self._hooks = load_hooks()
        from .permission_rules import PermissionRules
        self._perm_rules = PermissionRules.load()

    async def _emit(self, event: StreamEvent) -> None:
        result = self.event_sink(event)
        if result is not None:
            await result

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [t.to_schema() for t in self.session.tools]

    def _find_tool(self, name: str):
        for t in self.session.tools:
            if t.name == name:
                return t
        return None

    async def run_turn(self, user_text: str) -> None:
        from .hooks import fire_hook
        if self._hooks:
            try:
                await fire_hook(
                    self._hooks,
                    "UserPromptSubmit",
                    {"prompt": user_text, "cwd": self.session.cwd},
                )
            except Exception:
                pass

        from .compaction import compact_messages, should_compact
        if should_compact(self.session.messages):
            try:
                compacted = await compact_messages(
                    self.session.messages, self.session.provider
                )
                self.session.messages = compacted
            except Exception:
                pass

        self.session.append_user_text(user_text)
        await self._drive_loop()

    async def fire_session_start(self) -> None:
        from .hooks import fire_hook
        if self._hooks:
            try:
                await fire_hook(
                    self._hooks,
                    "SessionStart",
                    {"session_id": self.session.session_id, "cwd": self.session.cwd},
                )
            except Exception:
                pass

    async def fire_session_end(self) -> None:
        from .hooks import fire_hook
        if self._hooks:
            try:
                await fire_hook(
                    self._hooks,
                    "SessionEnd",
                    {"session_id": self.session.session_id, "cwd": self.session.cwd},
                )
            except Exception:
                pass

    async def _drive_loop(self) -> None:
        """Drive the provider ↔ tool loop using whatever is already in session.messages."""
        while True:
            assistant_blocks: list[Block] = []
            current_text: list[str] = []
            tool_uses: list[ToolUseBlock] = []
            stop_reason = "end_turn"

            stream = self.session.provider.stream(
                messages=self.session.messages,
                system=self.system_prompt,
                tools=self._tool_schemas(),  # type: ignore[arg-type]
            )

            async for event in stream:
                await self._emit(event)

                if isinstance(event, TextDelta):
                    current_text.append(event.text)
                elif isinstance(event, ToolUseEnd):
                    if current_text:
                        assistant_blocks.append(TextBlock(text="".join(current_text)))
                        current_text = []
                    block = ToolUseBlock(id=event.id, name=event.name, input=event.input, _raw_part=getattr(event, "_raw_part", None))
                    assistant_blocks.append(block)
                    tool_uses.append(block)
                elif isinstance(event, Usage):
                    self.session.add_tokens(event.input_tokens, event.output_tokens)
                elif isinstance(event, MessageStop):
                    stop_reason = event.stop_reason

            if current_text:
                assistant_blocks.append(TextBlock(text="".join(current_text)))

            self.session.append_assistant_message(assistant_blocks)

            if not tool_uses:
                return

            tool_results = await self._run_tool_uses(tool_uses)
            self.session.append_tool_results(tool_results)

            if stop_reason not in ("tool_use", "end_turn"):
                return

    async def _run_tool_uses(self, tool_uses: list[ToolUseBlock]) -> list[ToolResultBlock]:
        """Execute a batch of tool calls.

        Read-only tools in the same batch run in parallel via asyncio.gather.
        Destructive tools run sequentially in the order the model emitted them.
        Results are returned in the original order so the conversation history
        keeps its tool_use → tool_result pairing stable.
        """
        import asyncio
        from .tools.base import ToolContext

        ctx = ToolContext(
            session=self.session,
            request_permission=self.permission_cb,
        )

        results: list[ToolResultBlock | None] = [None] * len(tool_uses)

        parallel_indices: list[int] = []
        sequential_indices: list[int] = []
        for i, use in enumerate(tool_uses):
            tool = self._find_tool(use.name)
            if tool is not None and tool.is_read_only:
                parallel_indices.append(i)
            else:
                sequential_indices.append(i)

        if parallel_indices:
            coros = [self._execute_one(tool_uses[i], ctx) for i in parallel_indices]
            parallel_results = await asyncio.gather(*coros, return_exceptions=False)
            for i, block in zip(parallel_indices, parallel_results):
                results[i] = block

        for i in sequential_indices:
            results[i] = await self._execute_one(tool_uses[i], ctx)

        # Emit tool result events in original order so the UI stays coherent
        for i, use in enumerate(tool_uses):
            block = results[i]
            if block is None:
                block = ToolResultBlock(
                    tool_use_id=use.id,
                    content="internal: missing result",
                    is_error=True,
                )
                results[i] = block
            await self._emit(
                ToolResultEvent(
                    tool_use_id=use.id,
                    tool_name=use.name,
                    content=block.content,
                    is_error=block.is_error,
                )
            )

        return [r for r in results if r is not None]

    async def _execute_one(
        self, use: ToolUseBlock, ctx
    ) -> ToolResultBlock:
        """Run one tool call end-to-end: hooks, permission, execution."""
        from .hooks import fire_hook

        tool = self._find_tool(use.name)
        if tool is None:
            return ToolResultBlock(
                tool_use_id=use.id,
                content=f"unknown tool: {use.name}",
                is_error=True,
            )

        if self._hooks:
            try:
                result = await fire_hook(
                    self._hooks,
                    "PreToolUse",
                    {"tool_name": use.name, "input": use.input},
                )
                if result and result.block:
                    return ToolResultBlock(
                        tool_use_id=use.id,
                        content=f"blocked by PreToolUse hook: {result.stderr or result.stdout}",
                        is_error=True,
                    )
            except Exception:
                pass

        # Check user permission rules first (~/.claude/settings.json)
        rule_decision = self._perm_rules.evaluate(use.name, use.input)
        if rule_decision == "deny":
            return ToolResultBlock(
                tool_use_id=use.id,
                content=f"permission denied by rule in {self._perm_rules.__class__.__module__}",
                is_error=True,
            )
        if rule_decision == "allow":
            pass  # skip to execution
        else:
            decision = await tool.check_permissions(use.input, ctx)
            if decision.behavior == "deny":
                return ToolResultBlock(
                    tool_use_id=use.id,
                    content=f"permission denied: {decision.reason or 'no reason given'}",
                    is_error=True,
                )
            if decision.behavior == "ask" or rule_decision == "ask":
                allowed = await self.permission_cb(use.name, use.input)
                if not allowed:
                    return ToolResultBlock(
                        tool_use_id=use.id,
                        content="user denied permission",
                        is_error=True,
                    )

        try:
            output = await tool.run(use.input, ctx)
            content = output if isinstance(output, str) else str(output)
            is_error = content.startswith("error:")
            block = ToolResultBlock(
                tool_use_id=use.id, content=content, is_error=is_error
            )
        except Exception as exc:  # noqa: BLE001
            block = ToolResultBlock(
                tool_use_id=use.id,
                content=f"{type(exc).__name__}: {exc}",
                is_error=True,
            )

        if self._hooks:
            try:
                await fire_hook(
                    self._hooks,
                    "PostToolUse",
                    {"tool_name": use.name, "input": use.input},
                )
            except Exception:
                pass

        return block
