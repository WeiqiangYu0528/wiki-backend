# Session Lifecycle

## Overview

A session in Claude Code represents a single continuous conversation between the user and the model, from initial bootstrap through interactive turns, optional backgrounding, and eventual termination or resumption. The session lifecycle governs state initialization, transcript persistence, context loading, hook execution, and the mechanisms that allow a session to be paused, resumed, or recovered after interruption. Understanding this lifecycle is essential for reasoning about when state is initialized, how data flows between turns, and what guarantees hold across session boundaries.

## Mechanism

### Bootstrap

The entry point is `main.tsx`, which orchestrates a carefully ordered startup sequence designed for minimal latency:

1. **Profiling checkpoint**: `profileCheckpoint('main_tsx_entry')` marks the earliest entry point.
2. **Parallel prefetches**: MDM raw reads (`startMdmRawRead()`), keychain prefetch (`startKeychainPrefetch()`), GrowthBook initialization, AWS/GCP credential prefetch, and fast-mode status prefetch are all kicked off concurrently during import evaluation.
3. **CLI parsing**: Commander processes command-line arguments (`--resume`, `--continue`, `--agent`, `--model`, `--permission-mode`, etc.).
4. **Trust and auth**: The trust dialog acceptance check and authentication validation run before any API calls.
5. **Context loading**: `getUserContext()` and `getSystemContext()` are resolved to build the system prompt with CLAUDE.md hierarchy, environment details, and git status.
6. **Tool registration**: `getTools()` assembles the available tool pool, including MCP tools from configured servers.
7. **Session start hooks**: `processSessionStartHooks('startup')` executes plugin hooks and user-configured hooks, collecting additional context messages and watch paths.

The `init()` function (from `entrypoints/init.ts`) handles the core bootstrap: setting the session ID, original cwd, model overrides, and agent type in the global bootstrap state module.

### State Initialization

Session state is managed through `AppState`, a React-style state object that flows through the component tree. Key state includes:

- `toolPermissionContext`: Permission mode, always-allow rules, additional working directories.
- `effortValue`: Model effort level (low/medium/high or integer budget tokens).
- `standaloneAgentContext`: Agent name and color when running as a standalone agent.
- `todos`: TodoWrite state for tracking task progress.
- `fileHistory`: File change tracking for undo/attribution.
- `attribution`: Commit attribution state (ant-only).

The `SessionState` type (`sessionState.ts`) tracks the runtime phase: `'idle'`, `'running'`, or `'requires_action'`. The `requires_action` state carries `RequiresActionDetails` with tool name, description, and input so downstream surfaces (CCR sidebar, push notifications) can display what the session is blocked on.

`SessionExternalMetadata` captures published state for remote consumers: `permission_mode`, `model`, `pending_action`, `post_turn_summary`, and `task_summary`.

### Session Persistence

Every message exchanged during a session is persisted to a JSONL transcript file managed by `sessionStorage.ts`. Key aspects:

- **Transcript path**: Determined by `getTranscriptPath()`, stored under the Claude config home directory organized by session ID.
- **Append-only logging**: Messages are appended via `fsAppendFile` for crash safety. The file is never rewritten in place during normal operation.
- **Metadata**: Session metadata (cwd, model, agent type, permission mode, version, worktree state) is recorded as structured log entries alongside messages.
- **Subagent transcripts**: Each subagent writes to a separate transcript file under a `subagents/` subdirectory, tracked by agent ID. The `setAgentTranscriptSubdir()` function supports grouping related subagent transcripts (e.g., workflow runs).
- **Content replacement records**: Large tool results that were replaced with stubs for prompt cache stability are tracked separately so they can be restored on resume.

### Transcript Recording

The `recordSidechainTranscript()` function writes subagent message streams to disk as they are yielded. For the main thread, messages are appended directly to the session transcript. The recording pipeline handles:

- Assistant messages with usage data
- User messages (including tool results)
- Progress messages
- System compact boundary messages (marking compaction points)
- File history snapshots
- Attribution snapshots
- Context collapse commit entries

### Session Recovery and Resume

Sessions can be resumed via `--resume <session-id>` or `--continue` (most recent session). The resume flow in `sessionRestore.ts`:

1. **Transcript loading**: `readTranscriptForLoad()` (from `sessionStoragePortable.ts`) reads the JSONL transcript, handling large files via head/tail optimization (`SKIP_PRECOMPACT_THRESHOLD`).
2. **Message reconstruction**: Serialized messages are deserialized back into the `Message[]` array with proper typing.
3. **State restoration**: `restoreSessionStateFromLog()` rebuilds:
   - File history from snapshots
   - Attribution state from snapshots (ant-only)
   - Context collapse commit log and staged snapshot
   - TodoWrite state by scanning the transcript for the last `TodoWrite` tool_use block
4. **Bootstrap state update**: `switchSession()` updates the global session ID, `setOriginalCwd()` restores the working directory, `setMainLoopModelOverride()` restores the model, and `setMainThreadAgentType()` restores the agent.
5. **Agent restoration**: `restoreAgentSetting()` re-applies custom agent type and model override from the resumed session's metadata.
6. **Cost state**: `restoreCostStateForSession()` reloads cost tracking data.
7. **Worktree restoration**: `restoreWorktreeSession()` handles sessions that were running in isolated worktrees.
8. **Session start hooks re-execution**: `processSessionStartHooks('resume')` runs hooks again with the `'resume'` source so hooks can differentiate between fresh starts and resumes.

### Session Backgrounding

Session activity tracking (`sessionActivity.ts`) uses a refcount-based heartbeat timer:

- `startSessionActivity()` / `stopSessionActivity()` bracket API calls and tool execution.
- When the refcount is positive, a heartbeat fires every 30 seconds (`SESSION_ACTIVITY_INTERVAL_MS`) to keep remote containers alive.
- Keep-alive sending is gated behind `CLAUDE_CODE_REMOTE_SEND_KEEPALIVES`.
- After the refcount drops to zero, a 30-second idle timer logs a diagnostic event.

For remote sessions (CCR), the session can be backgrounded while work continues. The `SessionExternalMetadata` system publishes state transitions and progress summaries so external UI can track what a backgrounded session is doing.

## Involved Entities

- [main.tsx](../claude_code/src/main.tsx) -- CLI entry point, bootstrap orchestration
- [Session Storage](../claude_code/src/utils/sessionStorage.ts) -- transcript persistence, metadata recording
- [Session Restore](../claude_code/src/utils/sessionRestore.ts) -- resume logic, state reconstruction
- [Session Start](../claude_code/src/utils/sessionStart.ts) -- hook execution on startup/resume/clear/compact
- [Session State](../claude_code/src/utils/sessionState.ts) -- runtime phase tracking, external metadata
- [Session Activity](../claude_code/src/utils/sessionActivity.ts) -- heartbeat keep-alive for remote sessions
- [Session Storage Portable](../claude_code/src/utils/sessionStoragePortable.ts) -- cross-platform transcript reading
- [Session History](../claude_code/src/assistant/sessionHistory.ts) -- session listing and history
- [Session Hooks](../claude_code/src/utils/hooks/sessionHooks.ts) -- session-scoped hook registration
- [Bridge Session Runner](../claude_code/src/bridge/sessionRunner.ts) -- SDK session execution bridge

## Source Evidence

- `main.tsx:1-9` fires profiling, MDM reads, and keychain prefetch as side effects during import evaluation for maximum parallelism.
- `sessionState.ts:1` defines `SessionState = 'idle' | 'running' | 'requires_action'`.
- `sessionState.ts:15-24` defines `RequiresActionDetails` with `tool_name`, `action_description`, `tool_use_id`, `request_id`, and optional `input`.
- `sessionRestore.ts:77-93` extracts TodoWrite state by scanning the transcript backward for the last `TodoWrite` tool_use block.
- `sessionRestore.ts:99-150` restores file history, attribution, context collapse, and todo state from log entries.
- `sessionStart.ts:35-36` signature: `processSessionStartHooks(source: 'startup' | 'resume' | 'clear' | 'compact', ...)`.
- `sessionActivity.ts:18` sets `SESSION_ACTIVITY_INTERVAL_MS = 30_000` for the heartbeat timer.
- `sessionStorage.ts:32-33` imports `getSessionId`, `isSessionPersistenceDisabled` from bootstrap state.

## See Also

- [Compaction and Context Management](./compaction-and-context-management.md) -- compaction is a major session lifecycle event
- [Agent Isolation](./agent-isolation.md) -- subagent sessions have their own transcripts and lifecycle
- [Frontmatter Conventions](./frontmatter-conventions.md) -- agent/skill definitions that configure session behavior
