"""Agent loop: drives one user turn through the model + tools to end_turn."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from .messages import (
    Block,
    Message,
    MessageStop,
    StatusEvent,
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


class _StreamTimeout(Exception):
    """Raised when the model stream exceeds liveness or total timeout."""


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

    def _build_todo_nudge(self) -> str:
        try:
            from .tools.todowrite import _load_persisted_todos
        except Exception:
            return ""

        todos = _load_persisted_todos(self.session.session_id)
        incomplete_count = 0
        for todo in todos:
            if not isinstance(todo, dict):
                continue
            status = str(todo.get("status") or "").strip().lower()
            if status != "completed":
                incomplete_count += 1
        if incomplete_count == 0:
            return ""
        suffix = "" if incomplete_count == 1 else "s"
        return (
            f"You have {incomplete_count} incomplete task{suffix} in your TodoWrite list. "
            "Make sure to complete all tasks before ending your response."
        )

    def _assistant_has_visible_text_since(self, start_index: int) -> bool:
        for message in getattr(self.session, "messages", [])[start_index:]:
            if getattr(message, "role", "") != "assistant":
                continue
            if any(
                isinstance(block, TextBlock) and block.text.strip()
                for block in getattr(message, "content", [])
            ):
                return True
        return False

    def _system_prompt_for_turn(self, turn: int) -> str:
        system_prompt = self.system_prompt
        if turn <= 2:
            return system_prompt

        todo_nudge = self._build_todo_nudge().strip()
        if not todo_nudge:
            return system_prompt
        if todo_nudge in system_prompt:
            return system_prompt
        return system_prompt.rstrip() + "\n\n" + todo_nudge

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

    MAX_TOOL_LOOP_ITERATIONS = 40
    STREAM_LIVENESS_TIMEOUT = 45  # seconds — no event for this long → dead
    STREAM_TOTAL_TIMEOUT = 300    # seconds — max total time per model call
    MAX_TOKENS_RECOVERY_LIMIT = 3
    MAX_TOKENS_RECOVERY_MSG = (
        "Output token limit hit. Resume directly — no apology, no recap of what "
        "you were doing. Pick up mid-thought if that is where the cut happened. "
        "Break remaining work into smaller pieces."
    )

    @staticmethod
    def _reactive_compact_enabled() -> bool:
        import os

        value = os.getenv("CLAURST_FEATURE_REACTIVE_COMPACT", "")
        return value.strip().lower() in {"1", "true", "yes", "on"}

    async def _post_usage_compaction(self, stop_reason: str) -> None:
        from .compaction import (
            AutoCompactState,
            auto_compact_if_needed,
            context_collapse,
            context_window_for_model,
            reactive_compact,
            should_compact,
            should_context_collapse,
        )

        if not self.session.model_messages:
            return
        tokens_used = int(getattr(self.session, "last_input_tokens", 0) or 0)
        if tokens_used <= 0:
            return
        model = str(getattr(self.session.provider, "model", "") or "")

        if self._reactive_compact_enabled():
            context_limit = context_window_for_model(model)
            if should_context_collapse(tokens_used, context_limit):
                try:
                    result = await context_collapse(
                        self.session.model_messages,
                        self.session.provider,
                        model,
                        session=self.session,
                    )
                except Exception:
                    return
                self.session.model_messages = result.messages
                return

            if should_compact(tokens_used, context_limit):
                try:
                    result = await reactive_compact(
                        self.session.model_messages,
                        self.session.provider,
                        model,
                        session=self.session,
                    )
                except Exception:
                    return
                self.session.model_messages = result.messages
                return
            return

        if stop_reason not in ("end_turn", "tool_use"):
            return

        state = getattr(self.session, "auto_compact_state", None)
        if not isinstance(state, AutoCompactState):
            state = AutoCompactState()
            setattr(self.session, "auto_compact_state", state)
        new_messages = await auto_compact_if_needed(
            self.session.provider,
            self.session.model_messages,
            tokens_used,
            model,
            state,
            session=self.session,
        )
        if new_messages is not None:
            self.session.model_messages = new_messages

    async def _maybe_trigger_auto_dream(self) -> None:
        import asyncio
        import json

        from .auto_dream import AutoDream
        from .tools.agent_tool import AgentTool, get_coordination_root, get_subagent_registry
        from .tools.base import ToolContext

        if get_coordination_root(self.session) is not self.session:
            return

        cwd = (self.session.cwd or "").strip()
        if not cwd:
            return

        dreamer = AutoDream.for_project(cwd)
        try:
            task = await dreamer.maybe_trigger()
        except Exception:
            return
        if task is None:
            return

        tool = AgentTool()
        ctx = ToolContext(session=self.session, request_permission=self.permission_cb)
        payload = {
            "description": "memory consolidation",
            "prompt": task.prompt,
            "max_turns": 20,
            "system_prompt": (
                "You are performing automatic memory consolidation. "
                "Complete the task and return a brief summary."
            ),
            "run_in_background": True,
            "isolation": None,
            "_bash_read_only": True,
        }
        try:
            result = await tool.run(payload, ctx)
            data = json.loads(result)
            agent_id = str(data.get("agent_id") or "").strip()
        except Exception:
            await AutoDream.finish_consolidation(task)
            return

        registry = get_subagent_registry(self.session)
        entry = registry.get(agent_id)
        running_task = entry.get("task") if isinstance(entry, dict) else None
        if running_task is None:
            await AutoDream.finish_consolidation(task)
            return

        async def finalize() -> None:
            try:
                await asyncio.shield(running_task)
            finally:
                await AutoDream.finish_consolidation(task)

        asyncio.create_task(finalize())

    async def _drive_loop(self) -> None:
        """Drive the provider ↔ tool loop using whatever is already in session.messages."""
        import asyncio
        from .tools.agent_tool import drain_coordinator_messages, get_coordination_root

        turns = 0
        run_start_message_count = len(getattr(self.session, "messages", []))
        max_tokens_recovery_count = 0
        stall_retries_left = max(0, int(getattr(self.session, "stream_stall_retries", 2) or 0))
        effective_max_turns = max(
            1,
            int(getattr(self.session, "max_turns", self.MAX_TOOL_LOOP_ITERATIONS) or self.MAX_TOOL_LOOP_ITERATIONS),
        )
        while True:
            turns += 1
            if turns > effective_max_turns:
                notice = f"Reached maximum turn limit ({effective_max_turns})."
                await self._emit(StatusEvent(text=notice))
                if not self._assistant_has_visible_text_since(run_start_message_count):
                    await self._emit(TextDelta(text=notice))
                    self.session.append_assistant_message([TextBlock(text=notice)])
                return

            for text in list(getattr(self.session, "pending_messages", [])):
                content = (text or "").strip()
                if content:
                    self.session.append_user_text(content)
            getattr(self.session, "pending_messages", []).clear()

            command_queue = getattr(self.session, "command_queue", None)
            if command_queue is not None and not command_queue.is_empty():
                injected_messages = command_queue.drain_to_messages()
                if injected_messages:
                    self.session.model_messages = injected_messages + list(self.session.model_messages)

            if get_coordination_root(self.session) is self.session:
                injected_messages = drain_coordinator_messages(self.session)
                for item in injected_messages:
                    sender = str(item.get("from") or "coordinator")
                    summary = str(item.get("summary") or "").strip()
                    suffix = f" ({summary})" if summary else ""
                    content = str(item.get("content") or "").strip()
                    if content:
                        self.session.append_user_text(
                            f"[Agent message from {sender}{suffix}]\n{content}"
                        )

            budget = max(0, int(getattr(self.session, "tool_result_budget", 0) or 0))
            if budget > 0:
                self.session.model_messages, _ = self._apply_tool_result_budget(
                    self.session.model_messages,
                    budget,
                )

            assistant_blocks: list[Block] = []
            current_text: list[str] = []
            tool_uses: list[ToolUseBlock] = []
            stop_reason = "end_turn"

            stream = self.session.provider.stream(
                messages=self.session.model_messages,
                system=self._system_prompt_for_turn(turns),
                tools=self._tool_schemas(),  # type: ignore[arg-type]
                temperature=getattr(self.session, "temperature", None),
                top_p=getattr(self.session, "top_p", None),
                top_k=getattr(self.session, "top_k", None),
                stop_sequences=list(getattr(self.session, "stop_sequences", []) or []),
                thinking_budget=(
                    getattr(self.session, "thinking_budget", None)
                    if getattr(self.session, "thinking_budget", None) is not None
                    else getattr(self.session.provider, "thinking_budget", None)
                ),
                provider_options=dict(getattr(self.session, "provider_options", {}) or {}),
            )

            timed_out = False
            timeout_reason = ""
            try:
                async for event in self._stream_with_liveness(stream):
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
                        self.session.add_tokens(
                            event.input_tokens,
                            event.output_tokens,
                            event.cache_creation_input_tokens,
                            event.cache_read_input_tokens,
                            model=getattr(self.session.provider, "model", ""),
                        )
                    elif isinstance(event, MessageStop):
                        stop_reason = event.stop_reason
            except _StreamTimeout as exc:
                timed_out = True
                timeout_reason = str(exc)

            if current_text:
                assistant_blocks.append(TextBlock(text="".join(current_text)))

            if timed_out:
                if stall_retries_left > 0:
                    stall_retries_left -= 1
                    turns -= 1
                    await self._emit(
                        StatusEvent(
                            text=(
                                f"No response for {self.STREAM_LIVENESS_TIMEOUT}s — "
                                f"retrying ({stall_retries_left + 1} left)…"
                            )
                        )
                    )
                    continue
                raise RuntimeError(timeout_reason)
            stall_retries_left = max(0, int(getattr(self.session, "stream_stall_retries", 2) or 0))

            self.session.append_assistant_message(assistant_blocks)
            await self._post_usage_compaction(stop_reason)

            if not tool_uses:
                if stop_reason == "max_tokens":
                    if max_tokens_recovery_count < self.MAX_TOKENS_RECOVERY_LIMIT:
                        max_tokens_recovery_count += 1
                        turns -= 1
                        await self._emit(
                            StatusEvent(
                                text=(
                                    "Output token limit hit — continuing "
                                    f"(attempt {max_tokens_recovery_count}/{self.MAX_TOKENS_RECOVERY_LIMIT})"
                                )
                            )
                        )
                        self.session.append_message(
                            "user",
                            [TextBlock(text=self.MAX_TOKENS_RECOVERY_MSG)],
                            include_in_transcript=False,
                            include_in_model=True,
                        )
                        continue
                if stop_reason == "end_turn":
                    await self._maybe_trigger_auto_dream()
                return

            max_tokens_recovery_count = 0
            tool_results = await self._run_tool_uses(tool_uses)
            self.session.append_tool_results(tool_results)

            if stop_reason not in ("tool_use", "end_turn"):
                return

    @staticmethod
    def _tool_result_chars(block: Block) -> int:
        if isinstance(block, ToolResultBlock):
            return len(block.content or "")
        return 0

    def _apply_tool_result_budget(
        self,
        messages: list[Message],
        budget: int,
    ) -> tuple[list[Message], int]:
        total_chars = sum(
            self._tool_result_chars(block)
            for message in messages
            if message.role == "user"
            for block in message.content
        )
        if total_chars <= budget:
            return messages, 0

        to_shed = total_chars - budget
        truncated = 0
        new_messages: list[Message] = []
        for message in messages:
            if message.role != "user":
                new_messages.append(
                    Message(
                        role=message.role,
                        content=list(message.content),
                        uuid=message.uuid,
                    )
                )
                continue

            new_blocks: list[Block] = []
            for block in message.content:
                if isinstance(block, ToolResultBlock) and to_shed > 0:
                    size = len(block.content or "")
                    if size > 0:
                        new_blocks.append(
                            ToolResultBlock(
                                tool_use_id=block.tool_use_id,
                                content="[tool result truncated to save context]",
                                is_error=block.is_error,
                            )
                        )
                        truncated += 1
                        to_shed = max(0, to_shed - size)
                        continue
                new_blocks.append(block)
            new_messages.append(
                Message(
                    role=message.role,
                    content=new_blocks,
                    uuid=message.uuid,
                )
            )
        return new_messages, truncated

    async def _stream_with_liveness(self, stream):
        """Wrap an async stream with liveness + total timeout (CC pattern).

        Raises _StreamTimeout if:
        - No event received for STREAM_LIVENESS_TIMEOUT seconds
        - Total stream time exceeds STREAM_TOTAL_TIMEOUT seconds
        """
        import asyncio

        aiter = stream.__aiter__()
        start = asyncio.get_event_loop().time()
        while True:
            now = asyncio.get_event_loop().time()
            elapsed = now - start
            if elapsed > self.STREAM_TOTAL_TIMEOUT:
                raise _StreamTimeout(
                    f"model stream total timeout ({self.STREAM_TOTAL_TIMEOUT}s)"
                )
            remaining_total = self.STREAM_TOTAL_TIMEOUT - elapsed
            chunk_timeout = min(self.STREAM_LIVENESS_TIMEOUT, remaining_total)
            try:
                event = await asyncio.wait_for(
                    aiter.__anext__(), timeout=chunk_timeout
                )
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError:
                raise _StreamTimeout(
                    f"no stream event for {self.STREAM_LIVENESS_TIMEOUT}s — connection likely dead"
                )
            yield event

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
        from .permission_rules import evaluate_permission

        level = tool.get_permission_level()
        perm_decision, perm_reason = evaluate_permission(
            self.session,
            self._perm_rules,
            use.name,
            use.input,
            level,
        )
        if perm_decision == "deny":
            denial_log = getattr(self.session, "permission_denials", None)
            if isinstance(denial_log, list):
                denial_log.append(
                    {
                        "tool_name": use.name,
                        "reason": perm_reason or "permission denied",
                    }
                )
            return ToolResultBlock(
                tool_use_id=use.id,
                content=perm_reason or "permission denied",
                is_error=True,
            )

        decision = await tool.check_permissions(use.input, ctx)
        if decision.behavior == "deny":
            denial_log = getattr(self.session, "permission_denials", None)
            if isinstance(denial_log, list):
                denial_log.append(
                    {
                        "tool_name": use.name,
                        "reason": decision.reason or "permission denied",
                    }
                )
            return ToolResultBlock(
                tool_use_id=use.id,
                content=f"permission denied: {decision.reason or 'no reason given'}",
                is_error=True,
            )

        ask_needed = perm_decision == "ask" or decision.behavior == "ask"
        if perm_decision != "allow" and decision.behavior == "allow":
            ask_needed = False

        if ask_needed:
            allowed = await self.permission_cb(use.name, use.input)
            if not allowed:
                denial_log = getattr(self.session, "permission_denials", None)
                if isinstance(denial_log, list):
                    denial_log.append(
                        {
                            "tool_name": use.name,
                            "reason": perm_reason or "user denied permission",
                        }
                    )
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
