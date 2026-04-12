# OpenH Core Parity Audit

Last updated: 2026-04-12

Reference roots:

- `/Users/hyeon/Projects/cc-leaked-fresh/src-rust`
- `/Users/hyeon/Projects/claude_code_pb/on/src-rust`

Status legend:

- `[x] reviewed` = line-by-line diff check already done against at least one public reference file
- `[~] reviewed-open` = line-by-line diff check done, but known parity gaps still remain
- `[ ] unreviewed` = not yet fully audited line-by-line
- `[-] local-only` = OpenH-only surface, not a direct parity target

## 1. Query / Engine

| Status | OpenH file | Primary public reference | Notes |
| --- | --- | --- | --- |
| `[~]` | `openh/agent.py` | `crates/query/src/lib.rs` | Reviewed multiple times. `max_turns`, `tool_result_budget`, command queue, compact trigger, AutoDream hook, todo nudge, and retry/max-token status surface checked. Still not a generator/state-machine architecture. |
| `[~]` | `openh/session.py` | `crates/query/src/lib.rs`, `crates/core/src/lib.rs` | Reviewed for max_turns, managed executor config, usage rollup. Still simpler than reference config graph. |
| `[~]` | `openh/compaction.py` | `crates/query/src/compact.rs` | Reviewed and ported major compact paths. Still needs continuous re-check for exact prompt text and failure semantics. |
| `[~]` | `openh/auto_dream.py` | `crates/query/src/auto_dream.rs` | Reviewed and wired into turn-end flow. Layout/storage assumptions still differ from reference. |
| `[~]` | `openh/command_queue.py` | `crates/query/src/command_queue.rs` | Reviewed. Core behavior exists, but full surrounding runtime surface still simpler. |
| `[~]` | `openh/coordinator.py` | `crates/query/src/coordinator.rs`, `crates/query/src/managed_orchestrator.rs` | Reviewed. Prompt/runtime split improved, but coordinator surface is still not fully exact. |
| `[~]` | `openh/session_memory.py` | `crates/query/src/session_memory.rs` | Reviewed. UUID cursor added. Extraction/storage logic still lighter than reference. |
| `[~]` | `openh/cc_compat.py` | `crates/core/src/session_storage.rs`, `crates/core/src/sqlite_storage.rs` | Reviewed this pass. Transcript root now prefers public-style `projects/<base64url(cwd)>`, last-prompt/custom-title/tombstone entries are understood, tail metadata + writer parent-UUID recovery were added, and legacy `sessions/` paths still resolve for backwards compatibility. Still no SQLite parity, no typed transcript union, and local `__meta__` append-only state remains OpenH-specific. |
| `[~]` | `openh/persistence.py` | `crates/core/src/lib.rs` persistent session helpers | Reviewed this pass. The legacy JSON session helpers now follow the public `sessions/*.json` shape more closely: UUID session IDs, `sessions_dir()/session_path()`, load/delete by ID, rename/tag/untag/search helpers, and broader message-content decoding. Still not the primary runtime path, and the stored session payload is much lighter than the public `ConversationSession` struct. |
| `[ ]` | `openh/commands.py` | `crates/commands/src/lib.rs` | Only selected commands checked. No full line audit yet. |

## 2. Prompt / Config / Message / Memory

| Status | OpenH file | Primary public reference | Notes |
| --- | --- | --- | --- |
| `[~]` | `openh/system_prompt.py` | `crates/core/src/system_prompt.rs` | Reviewed heavily. Dynamic boundary, output-style, coordinator prompt added. Still not guaranteed exact section-cache matrix everywhere. |
| `[~]` | `openh/config.py` | `crates/core/src/lib.rs`, `crates/core/src/output_styles.rs` | Reviewed for dotenv/model/system prompt loading. Still not a full parity pass. |
| `[~]` | `openh/messages.py` | `crates/core/src/lib.rs` | Reviewed. Message UUID added. Broader message type parity still needs continued audit. |
| `[~]` | `openh/memory.py` | `crates/core/src/claudemd.rs`, `crates/core/src/memdir.rs` | Reviewed around AGENTS/CLAUDE memory loading. Still lighter than reference memory stack. |
| `[ ]` | `openh/memdir.py` | `crates/core/src/memdir.rs` | Partial checks only. |
| `[~]` | `openh/output_styles.py` | `crates/core/src/output_styles.rs` | Reviewed for runtime style resolution. Plugin discovery path still incomplete. |
| `[ ]` | `openh/prompts.py` | `crates/core/src/prompt_history.rs` and command surfaces | Partial checks only. |
| `[ ]` | `openh/settings.py` | `crates/core/src/lib.rs`, `crates/core/src/output_styles.rs` | Partial checks only. |

## 3. Permission / Safety

| Status | OpenH file | Primary public reference | Notes |
| --- | --- | --- | --- |
| `[~]` | `openh/permission_rules.py` | `crates/core/src/lib.rs` | Reviewed again line-by-line. Manager-backed default behavior now matches public flow more closely: explicit deny/allow first, then mode fallback (`read -> allow`, `write/exec/network -> ask or deny`). Still not a literal `PermissionManager` port. |
| `[~]` | `openh/tools/bash_classifier.py` | `crates/core/src/bash_classifier.rs` | Reviewed. Safety logic exists, but parity needs more detailed rule-by-rule pass. |
| `[~]` | `openh/tools/bash.py` | `crates/tools/src/bash.rs`, `crates/tools/src/monitor_tool.rs` | Reviewed multiple times. Background monitor/notify paths added. Still not exact global registry architecture. |

## 4. Tool Runtime / Registry

| Status | OpenH file | Primary public reference | Notes |
| --- | --- | --- | --- |
| `[~]` | `openh/tools/base.py` | `crates/tools/src/lib.rs` | Reviewed. `resolve_path()` added to match public relative-path behavior. |
| `[~]` | `openh/tools/__init__.py` | `crates/tools/src/lib.rs` | Reviewed. Legacy `LS` removed from default built-ins because public built-ins do not expose it. |
| `[~]` | `openh/tools/agent_tool.py` | `crates/query/src/agent_tool.rs`, `crates/tools/src/agent_tool.rs` | Reviewed heavily. Permission level, max_turns, background mode, and worktree behavior checked. Background agents now use a one-shot poll helper surface and isolated worktrees are removed after both sync and background runs. Still not an exact Rust structure port. |
| `[~]` | `openh/tools/send_message.py` | `crates/tools/src/send_message.rs` | Reviewed. Mailbox/broadcast/status surface exists, and `__status__` now consumes finished background-agent results through the helper flow instead of reusing stale task state. |
| `[~]` | `openh/tools/task_tools.py` | `crates/tools/src/tasks.rs` | Reviewed. Task board added, but still lighter than public task model. |
| `[~]` | `openh/tools/todowrite.py` | `crates/tools/src/todo_write.rs` | Reviewed. Input/status parity partially matched. |
| `[~]` | `openh/tools/tool_search.py` | `crates/tools/src/tool_search.rs` | Reviewed. Keyword scoring improved. Deferred-loading parity still open. |
| `[~]` | `openh/tools/read.py` | `crates/tools/src/file_read.rs` | Reviewed. Relative-path parity fixed. |
| `[~]` | `openh/tools/write.py` | `crates/tools/src/file_write.rs` | Reviewed. Relative-path parity fixed. |
| `[~]` | `openh/tools/edit.py` | `crates/tools/src/file_edit.rs` | Reviewed. Relative-path parity fixed. |
| `[~]` | `openh/tools/glob.py` | `crates/tools/src/glob_tool.rs` | Reviewed. Relative-path parity fixed. |
| `[~]` | `openh/tools/grep.py` | `crates/tools/src/grep_tool.rs` | Reviewed. Relative-path parity fixed. |
| `[~]` | `openh/tools/notebook_edit.py` | `crates/tools/src/notebook_edit.rs` | Reviewed. Relative-path parity fixed. |
| `[~]` | `openh/tools/ask_user.py` | `crates/tools/src/ask_user.rs` | Reviewed earlier in tool parity pass, but worth another exact schema pass. |
| `[~]` | `openh/tools/planmode.py` | `crates/tools/src/enter_plan_mode.rs`, `crates/tools/src/exit_plan_mode.rs` | Reviewed earlier. Needs one more exact wording/schema pass. |
| `[~]` | `openh/tools/skill_tool.py` | `crates/tools/src/skill_tool.rs`, `crates/tools/src/bundled_skills.rs` | Reviewed earlier. Still open for full discovery parity. |
| `[ ]` | `openh/tools/webfetch.py` | `crates/tools/src/web_fetch.rs` | Not yet fully audited line-by-line. |
| `[ ]` | `openh/tools/websearch.py` | `crates/tools/src/web_search.rs` | Not yet fully audited line-by-line. |
| `[ ]` | `openh/tools/worktree.py` | `crates/tools/src/worktree.rs` | Partial checks only. |
| `[-]` | `openh/tools/ls.py` | none | Legacy local helper. Public built-in parity target does not include it. Kept in tree for compatibility, but no longer exposed by default. |
| `[-]` | `openh/tools/serial_tool.py` | none | FnD/local-only extension, not parity target. |
| `[-]` | `openh/tools/memory_tools.py` | none | OpenH-local helper surface. |

## 5. Providers / Usage / Cache Wiring

| Status | OpenH file | Primary public reference | Notes |
| --- | --- | --- | --- |
| `[~]` | `openh/providers/base.py` | `crates/query/src/lib.rs`, API client surfaces | Reviewed around compact/max_tokens wiring. |
| `[~]` | `openh/providers/anthropic.py` | public Anthropic request shaping in query/api path | Reviewed around system boundary/cache usage. Still lighter than reference stack. |
| `[~]` | `openh/providers/openai.py` | `crates/query/src/lib.rs`, `crates/api/src/providers/openai.rs` | Reviewed around tool-call reconstruction, stop-reason handling, and error surface. Request failures now bubble as errors instead of transcript text. |
| `[~]` | `openh/providers/gemini.py` | `crates/query/src/lib.rs`, `crates/api/src/providers/google.rs` | Reviewed around tool-call reconstruction, usage, and error surface. Request failures/retries no longer emit transcript text. Runtime smoke still depends on local `google.genai` availability. |
| `[ ]` | `openh/providers/__init__.py` | provider registry surfaces | Not yet fully audited. |

## 6. UI / Desktop Runtime

These are not strict engine parity targets, but they still matter for behavior and usability.

| Status | OpenH file | Primary public reference | Notes |
| --- | --- | --- | --- |
| `[ ]` | `openh/flet_app/main.py` | TUI/runtime surfaces only | Many spot checks and fixes done, but no full line-by-line audit of the whole file yet. |
| `[ ]` | `openh/flet_app/widgets.py` | TUI/runtime surfaces only | Many iterative fixes done, but still not fully audited line-by-line. |
| `[ ]` | `openh/flet_app/theme.py` | none | Local design system, not a direct public parity target. |
| `[ ]` | `openh/flet_app/settings_dialog.py` | command/settings surfaces | Partial checks only. |
| `[ ]` | `openh/flet_app/permission_dialog.py` | TUI permission dialog surfaces | Not fully audited. |

## 7. Clearly remaining parity work

These are the main open deltas after the reviewed files above:

1. Coordinator / managed-orchestrator prompt and runtime behavior still need another exact pass.
2. OpenAI/Gemini provider behavior is closer, but still needs more exact parity for unsupported-capability / provider-option edges.
3. Permission handler model is much closer, but still not a literal `PermissionManager` port.
4. Plugin-discovered output styles are still incomplete.
5. File-by-file audit is still missing for `commands.py`, `webfetch.py`, `websearch.py`, `worktree.py`, and most of `flet_app/*`.

## 8. Next audit order

Recommended next line-by-line audit batches:

1. `commands.py`
2. `webfetch.py`, `websearch.py`, `worktree.py`
3. `providers/openai.py`, `providers/gemini.py` edge-capability pass
4. `flet_app/main.py` and `flet_app/widgets.py` consistency sweep
5. `memdir.py`
