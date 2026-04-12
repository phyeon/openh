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
| `[~]` | `openh/coordinator.py` | `crates/query/src/coordinator.rs`, `crates/query/src/managed_orchestrator.rs` | Reviewed again this pass. Coordinator-mode env handling now accepts both the PB-style and fresh-style environment flags, worker filtering now also honors `CLAURST_SIMPLE`, and the local helper surface now includes the public-style `ScratchpadGate`. Still not a full managed-orchestrator runtime port. |
| `[~]` | `openh/session_memory.py` | `crates/query/src/session_memory.rs` | Reviewed. UUID cursor added. Extraction/storage logic still lighter than reference. |
| `[~]` | `openh/cc_compat.py` | `crates/core/src/session_storage.rs`, `crates/core/src/sqlite_storage.rs` | Reviewed this pass. Transcript root now prefers public-style `projects/<base64url(cwd)>`, last-prompt/custom-title/tombstone entries are understood, tail metadata + writer parent-UUID recovery were added, and legacy `sessions/` paths still resolve for backwards compatibility. Still no SQLite parity, no typed transcript union, and local `__meta__` append-only state remains OpenH-specific. |
| `[~]` | `openh/persistence.py` | `crates/core/src/lib.rs` persistent session helpers | Reviewed this pass. The legacy JSON session helpers now follow the public `sessions/*.json` shape more closely: UUID session IDs, `sessions_dir()/session_path()`, load/delete by ID, rename/tag/untag/search helpers, and broader message-content decoding. Still not the primary runtime path, and the stored session payload is much lighter than the public `ConversationSession` struct. |
| `[~]` | `openh/commands.py` | `crates/commands/src/lib.rs` | Reviewed this pass for the hot-path commands. Slash parsing now handles shell-style quoting, `/help <command>` works, `/model` accepts explicit model strings, `/compact` injects a synthetic compact request instead of directly forcing UI compaction, and `/rename` can auto-slug from current conversation state. Still much smaller than the public command surface (`/session`, `/resume`, `/usage`, `/permissions`, etc.). |

## 2. Prompt / Config / Message / Memory

| Status | OpenH file | Primary public reference | Notes |
| --- | --- | --- | --- |
| `[~]` | `openh/system_prompt.py` | `crates/core/src/system_prompt.rs` | Reviewed heavily. Dynamic boundary, output-style, coordinator prompt added. Still not guaranteed exact section-cache matrix everywhere. |
| `[~]` | `openh/config.py` | `crates/core/src/lib.rs`, `crates/core/src/output_styles.rs` | Reviewed for dotenv/model/system prompt loading. Still not a full parity pass. |
| `[~]` | `openh/messages.py` | `crates/core/src/lib.rs` | Reviewed. Message UUID added. Broader message type parity still needs continued audit. |
| `[~]` | `openh/memory.py` | `crates/core/src/claudemd.rs`, `crates/core/src/memdir.rs` | Reviewed again this pass. AGENTS/CLAUDE loading now follows the public scope order more closely (`managed -> user -> project -> local`), strips frontmatter, and expands `@include` directives with recursion/size guards. Still no mtime cache or richer metadata surface. |
| `[~]` | `openh/memdir.py` | `crates/core/src/memdir.rs` | Reviewed this pass. Recursive memory scanning, quick frontmatter parsing, MEMORY.md truncation, and index-only prompt injection now track the public memdir flow much more closely. Still does not expose the full public relevance-search helper surface. |
| `[~]` | `openh/output_styles.py` | `crates/core/src/output_styles.rs` | Reviewed again this pass. Runtime styles now also discover plugin-contributed `output-styles/` directories from installed Codex plugin roots, approximating the public plugin registry flow. Still no formal enabled-plugin registry or cache invalidation graph. |
| `[~]` | `openh/prompts.py` | `crates/core/src/output_styles.rs` and command/prompt surfaces | Reviewed this pass. Preset storage now separates stable slug from display label, writes explicit name metadata, and resolves old slug-based presets without breaking existing settings. Still an OpenH-local preset system, not a direct public prompt-history port. |
| `[~]` | `openh/settings.py` | `crates/core/src/lib.rs`, `crates/core/src/output_styles.rs` | Reviewed this pass. Settings now normalize/coerce persisted values, preserve unknown JSON keys on save so local writes do not clobber future settings fields, and include a local Gemini thinking-effort preference that maps onto the public low/medium/high/max budget ladder. Still a flatter OpenH-only schema than the public nested `Settings.config` graph. |

## 3. Permission / Safety

| Status | OpenH file | Primary public reference | Notes |
| --- | --- | --- | --- |
| `[~]` | `openh/permission_rules.py` | `crates/core/src/lib.rs` | Reviewed again line-by-line. Manager-backed default behavior now matches public flow more closely: explicit deny/allow first, then mode fallback (`read -> allow`, `write/exec/network -> ask or deny`). Non-interactive sessions now force the auto handler even if they inherit `interactive`, WebFetch/WebSearch rules now actually match URL/query patterns, coordinator-banned tools are denied at runtime for the manager session, and the rule/default split now lives in an explicit local `PermissionManager` object instead of being scattered across handlers. Still not a literal Rust port. |
| `[~]` | `openh/tools/bash_classifier.py` | `crates/core/src/bash_classifier.rs` | Reviewed. Safety logic exists, but parity needs more detailed rule-by-rule pass. |
| `[~]` | `openh/tools/bash.py` | `crates/tools/src/bash.rs`, `crates/tools/src/monitor_tool.rs` | Reviewed multiple times. Background monitor/notify paths added. Still not exact global registry architecture. |

## 4. Tool Runtime / Registry

| Status | OpenH file | Primary public reference | Notes |
| --- | --- | --- | --- |
| `[~]` | `openh/tools/base.py` | `crates/tools/src/lib.rs` | Reviewed. `resolve_path()` added to match public relative-path behavior. |
| `[~]` | `openh/tools/__init__.py` | `crates/tools/src/lib.rs` | Reviewed. Legacy `LS` removed from default built-ins because public built-ins do not expose it. |
| `[~]` | `openh/tools/agent_tool.py` | `crates/query/src/agent_tool.rs`, `crates/tools/src/agent_tool.rs` | Reviewed heavily. Permission level, max_turns, background mode, and worktree behavior checked. Background agents now use a one-shot poll helper surface, isolated worktrees are removed after both sync and background runs, Gemini sub-agents now inherit the parent's resolved thinking budget/runtime option, and worker tool selection now respects the coordinator/simple-mode filtering helpers instead of only dropping coordinator-only tools. Still not an exact Rust structure port. |
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
| `[~]` | `openh/tools/webfetch.py` | `crates/tools/src/web_fetch.rs` | Reviewed this pass. URL cache, edge-case HTML detection, and semantic extraction fallback were ported, and the cache now lives under `~/.claurst/web_cache` like the public ref. Still uses local provider wiring instead of the exact public API helper/client path. |
| `[~]` | `openh/tools/websearch.py` | `crates/tools/src/web_search.rs` | Reviewed this pass. Brave Search + DuckDuckGo fallback, `num_results`, and public-style result formatting were added. Still returns plain tool text instead of a richer result struct. |
| `[~]` | `openh/tools/worktree.py` | `crates/tools/src/worktree.rs` | Reviewed this pass. Schema, timestamped branch naming, `post_create_command`, `discard_changes`, and keep/remove exit semantics now track the public flow. Local runtime keeps worktree session state per OpenH session instead of a single global slot. |
| `[-]` | `openh/tools/ls.py` | none | Legacy local helper. Public built-in parity target does not include it. Kept in tree for compatibility, but no longer exposed by default. |
| `[-]` | `openh/tools/serial_tool.py` | none | FnD/local-only extension, not parity target. |
| `[~]` | `openh/tools/memory_tools.py` | none | OpenH-local helper surface. Reviewed this pass to better align with the memdir stack: memory listings now include filename and freshness metadata so the model can reason about stored memories with less ambiguity. Still not a public parity target. |

## 5. Providers / Usage / Cache Wiring

| Status | OpenH file | Primary public reference | Notes |
| --- | --- | --- | --- |
| `[~]` | `openh/providers/base.py` | `crates/query/src/lib.rs`, API client surfaces | Reviewed around compact/max_tokens wiring. |
| `[~]` | `openh/providers/anthropic.py` | public Anthropic request shaping in query/api path | Reviewed around system boundary/cache usage. Still lighter than reference stack. |
| `[~]` | `openh/providers/openai.py` | `crates/query/src/lib.rs`, `crates/api/src/providers/openai.rs` | Reviewed again this pass. Assistant text/tool-call conversion is closer to the public adapter now, and Responses-API-only models (`gpt-5*`, `o3*`, `o4*`) are now explicitly gated instead of being sent to Chat Completions. Chat Completions payload also uses `max_tokens` like the public adapter. Still no actual Responses API implementation. |
| `[~]` | `openh/providers/gemini.py` | `crates/query/src/lib.rs`, `crates/api/src/providers/google.rs` | Reviewed again this pass. Tool-call IDs now follow the public `call_<name>[_n]` pattern, duplicate streamed function-call chunks are coalesced before emitting tool-use events, `FINISH_REASON_UNSPECIFIED` maps cleanly to `end_turn`, Gemini model names now normalize `google/` and `models/` prefixes before hitting the SDK, and an optional `thinking_config` path now exists for Gemini 2.5+/3.x style budgets. Settings/runtime wiring now pushes Gemini effort into the provider, but the broader effort system is still smaller than the public stack. |
| `[~]` | `openh/providers/__init__.py` | provider registry surfaces | Reviewed this pass. Provider imports are now consistently lazy and missing-SDK failures surface as stable runtime errors instead of import crashes. Still a much smaller registry than the public provider module tree. |

## 6. UI / Desktop Runtime

These are not strict engine parity targets, but they still matter for behavior and usability.

| Status | OpenH file | Primary public reference | Notes |
| --- | --- | --- | --- |
| `[~]` | `openh/flet_app/main.py` | TUI/runtime surfaces only | Reviewed again this pass for hot-path UX parity. Transient actions like model/theme/init/mode-switch feedback now use a top-bar status surface instead of polluting the transcript, sub-agent permission requests now normalize back to the base tool name before rule matching/persistence, Gemini effort settings now propagate into the live provider, and the FnD wordmark was simplified to remove decorative eyebrow clutter. Still not a full file-wide audit. |
| `[~]` | `openh/flet_app/widgets.py` | TUI/runtime surfaces only | Reviewed this pass for sidebar/top bar/welcome/input behavior. FnD welcome layouts now diverge between dark and light themes, the sidebar new-chat button no longer swaps into a decorative emoji object, and the FnD top bar / welcome screen were simplified to remove extra labels and chrome. Still not a full file-wide audit. |
| `[ ]` | `openh/flet_app/theme.py` | none | Local design system, not a direct public parity target. |
| `[~]` | `openh/flet_app/settings_dialog.py` | `crates/tui/src/settings_screen.rs` and related settings surfaces | Reviewed this pass. Output-style picker now uses style labels, custom model values stay selectable instead of disappearing from the dropdown, prompt preset UI follows stable slug/display-name separation, and the token/settings tab now exposes Gemini thinking effort so runtime provider wiring can use public-style 0/5k/10k/20k budgets. Still a desktop/Flet-specific UI, not a literal port of the TUI settings screen. |
| `[~]` | `openh/flet_app/permission_dialog.py` | `crates/tui/src/dialogs.rs` | Reviewed again this pass. Dialog titles and previews are tool-specific, reason strings are now split into description + danger explanation like the public overlays, and the action set now matches the public flow more closely (`allow once`, `allow this session`, `always allow`, `deny`) with a Bash-only session prefix-allow affordance. Still a Flet modal rather than the TUI overlay implementation. |

## 7. Clearly remaining parity work

These are the main open deltas after the reviewed files above:

1. Coordinator / managed-orchestrator runtime still needs another exact pass beyond the current env/tool-filter parity helpers.
2. Permission handler model is much closer, but still not a literal Rust `PermissionManager` port.
3. Provider behavior is closer, but still needs more exact parity for unsupported-capability / provider-option edges and broader effort/thinking controls outside the current Gemini path.
4. File-by-file audit is still missing for parts of `flet_app/*`, plus a deeper follow-up on some provider and memory edges.

## 8. Next audit order

Recommended next line-by-line audit batches:

1. `coordinator.py` managed runtime exact pass
2. `permission_rules.py` literal Rust `PermissionManager` follow-up if needed
3. `providers/gemini.py` / broader effort controls final follow-up
4. `flet_app/main.py`, `flet_app/widgets.py` final regression watch after real usage
