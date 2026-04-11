# Task System

## Overview

The task management subsystem handles background and concurrent execution units within Claude Code. Seven task types support different execution models: local shell scripts, sub-agents, remote agents, in-process teammates, workflows, MCP monitors, and dream tasks (background memory consolidation). All tasks share a common lifecycle (`pending` -> `running` -> terminal) and are tracked in `AppState.tasks` as a flat record keyed by task ID. Output is streamed to per-task files on disk, and each task type implements its own `kill()` method for cleanup.

## Key Types

### TaskType

Seven discriminated string literals defined in `Task.ts`:

```typescript
type TaskType =
  | 'local_bash'
  | 'local_agent'
  | 'remote_agent'
  | 'in_process_teammate'
  | 'local_workflow'
  | 'monitor_mcp'
  | 'dream'
```

### TaskStatus

Five lifecycle states:

```typescript
type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'killed'
```

The helper `isTerminalTaskStatus()` returns `true` for `completed`, `failed`, and `killed`. It guards against injecting messages into dead teammates, evicting finished tasks, and orphan cleanup.

### TaskStateBase

Shared fields for all task states:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Unique ID, prefixed by type character |
| `type` | `TaskType` | Discriminator |
| `status` | `TaskStatus` | Current lifecycle state |
| `description` | `string` | Human-readable label |
| `toolUseId` | `string?` | Originating tool_use block ID |
| `startTime` | `number` | `Date.now()` at creation |
| `endTime` | `number?` | Set on terminal transition |
| `totalPausedMs` | `number?` | Accumulated pause time |
| `outputFile` | `string` | Path to disk output file |
| `outputOffset` | `number` | Byte offset for incremental reads |
| `notified` | `boolean` | Whether completion has been surfaced |

### Task ID Prefixes

Each type uses a single-character prefix followed by 8 random alphanumeric characters (36^8 ~ 2.8 trillion combinations):

| Prefix | Task Type |
|--------|-----------|
| `b` | `local_bash` |
| `a` | `local_agent` |
| `r` | `remote_agent` |
| `t` | `in_process_teammate` |
| `w` | `local_workflow` |
| `m` | `monitor_mcp` |
| `d` | `dream` |

### Task Interface

The runtime `Task` type exposes only the `kill()` method. Spawn and render were removed as they were never called polymorphically:

```typescript
type Task = {
  name: string
  type: TaskType
  kill(taskId: string, setAppState: SetAppState): Promise<void>
}
```

### TaskState Union

The `TaskState` union in `tasks/types.ts` combines all seven concrete state types: `LocalShellTaskState`, `LocalAgentTaskState`, `RemoteAgentTaskState`, `InProcessTeammateTaskState`, `LocalWorkflowTaskState`, `MonitorMcpTaskState`, and `DreamTaskState`. The `BackgroundTaskState` alias is identical and used for UI filtering via `isBackgroundTask()`.

## Task Types

### local_bash -- Background Shell Scripts

Executes shell commands in the background. Supports a `kind` discriminator (`'bash'` or `'monitor'`) for UI display variants. Spawned via `LocalShellSpawnInput` which carries `command`, `description`, optional `timeout`, and an optional `agentId` binding. Killed tasks suppress exit-code-137 notifications to avoid noise; SDK events are emitted directly instead.

### local_agent -- Sub-Agent Execution

Runs a sub-agent (or a backgrounded main session) in a sidebar panel. State extends `TaskStateBase` with `agentId`, `prompt`, `model`, `progress` (tool use count, token count, recent activities), `isBackgrounded`, `pendingMessages`, `retain`/`diskLoaded` for panel lifecycle, and `evictAfter` for GC scheduling. The `LocalMainSessionTask` variant (with `agentType: 'main-session'`) handles Ctrl+B backgrounding of the primary query. Messages can be injected mid-turn via `queuePendingMessage()` and drained at tool-round boundaries. Progress tracking computes token counts from cumulative input tokens plus summed output tokens.

### remote_agent -- Cloud Session Delegation

Delegates execution to a remote cloud session. Supports an `isUltraplan` flag with phase tracking (`plan_ready`, `needs_input`) that drives specialized footer-pill rendering with diamond indicators.

### in_process_teammate -- Concurrent Teammates

Shares the terminal with the main session. Teammates carry an `identity.teamName` used for pill label grouping. Foreground tasks (`isBackgrounded === false`) are excluded from the background task indicator.

### local_workflow -- Workflow Execution

Runs a multi-step workflow in the background. Appears in the footer pill as "background workflow(s)".

### monitor_mcp -- MCP Server Monitoring

Monitors an MCP server. Uses `kind: 'monitor'` display semantics shared with bash monitors. Pill label shows as "monitor(s)".

### dream -- Background Memory Consolidation

A UI-surfacing layer for the auto-dream (memory consolidation) subagent. The dream agent follows a four-stage internal structure (orient, gather, consolidate, prune) but the task only tracks two phases: `starting` and `updating` (flipped when the first Edit/Write tool_use lands). State includes `sessionsReviewing`, `filesTouched` (incomplete -- misses bash-mediated writes), `turns` (capped at 30 most recent), and `priorMtime` for consolidation lock rollback on kill. Dream tasks set `notified: true` immediately at completion since they have no model-facing notification path -- the inline system message serves as the user surface.

## Task Lifecycle

```
pending ──> running ──> completed
                   ├──> failed
                   └──> killed
```

Tasks are created via `createTaskStateBase()` in `pending` status, then immediately transitioned to `running` by their spawn function. Terminal transitions set `endTime` and, for agent tasks, schedule `evictAfter` for panel GC. The `isTerminalTaskStatus()` guard prevents further state mutations on terminal tasks.

## Persistence

- **Output files:** Streamed to `~/.claude/.out/task_${id}` via symlinks initialized by `initTaskOutputAsSymlink()`. Output paths are resolved by `getTaskOutputPath()`.
- **Incremental reads:** `outputOffset` tracks the byte position for reading new output since the last check.
- **Sidechain transcripts:** Agent tasks record conversation transcripts at paths resolved by `getAgentTranscriptPath()`. Panel viewing triggers a one-shot disk bootstrap (`diskLoaded` flag) that UUID-merges JSONL sidechain data into `messages`.
- **Eviction:** `evictTaskOutput()` cleans up disk output when tasks are killed or GC'd.

## Cleanup

Task termination is handled by `stopTask()` in `tasks/stopTask.ts`, which validates the task is running, dispatches to the type-specific `kill()` implementation, and optionally suppresses notifications:

1. **AbortController:** Each task holds an `AbortController`; `kill()` calls `abort()` to cancel in-flight work.
2. **Cleanup registry:** Agent tasks call `unregisterCleanup()` to remove their registered cleanup handler.
3. **State update:** Status set to `killed`, `endTime` stamped, `abortController` and `selectedAgent` cleared.
4. **Output eviction:** `evictTaskOutput()` removes the disk output file.
5. **SDK events:** For shell tasks, `emitTaskTerminatedSdk()` fires directly when the XML notification is suppressed.
6. **Dream-specific:** Rolls back the consolidation lock mtime via `rollbackConsolidationLock()` so the next session can retry.
7. **Child termination:** `killShellTasks.ts` handles terminating child bash processes spawned by agent tasks.

## Source Files

| File | Description |
|------|-------------|
| `Task.ts` | Core type definitions: `TaskType`, `TaskStatus`, `TaskStateBase`, `Task`, ID generation |
| `tasks/types.ts` | `TaskState` and `BackgroundTaskState` union types, `isBackgroundTask()` |
| `tasks/stopTask.ts` | Shared `stopTask()` logic with `StopTaskError` |
| `tasks/pillLabel.ts` | Footer pill label rendering for background tasks |
| `tasks/LocalShellTask/LocalShellTask.tsx` | Shell script task spawn, render, and kill |
| `tasks/LocalShellTask/guards.ts` | `LocalShellTaskState` type and type guards |
| `tasks/LocalShellTask/killShellTasks.ts` | Child bash process termination |
| `tasks/LocalAgentTask/LocalAgentTask.tsx` | Sub-agent task with progress tracking, message queuing, panel lifecycle |
| `tasks/LocalMainSessionTask.ts` | Main session backgrounding (Ctrl+B) as a `local_agent` variant |
| `tasks/RemoteAgentTask/RemoteAgentTask.tsx` | Remote/cloud session delegation with ultraplan support |
| `tasks/InProcessTeammateTask/InProcessTeammateTask.tsx` | In-process teammate task |
| `tasks/InProcessTeammateTask/types.ts` | `InProcessTeammateTaskState` type |
| `tasks/DreamTask/DreamTask.ts` | Dream (memory consolidation) task with phase and turn tracking |
| `utils/task/diskOutput.ts` | `getTaskOutputPath()`, `initTaskOutputAsSymlink()`, `evictTaskOutput()` |
| `utils/task/framework.ts` | `registerTask()`, `updateTaskState()`, `PANEL_GRACE_MS` |
| `utils/task/sdkProgress.ts` | `emitTaskProgress()` for SDK event streaming |

## See Also

- [Agent System](agent-system.md)
- [State Management](state-management.md)
- [Tool System](tool-system.md)
- [Task Execution and Isolation](../syntheses/task-execution-and-isolation.md)
