# Task Execution and Isolation

## Overview

This synthesis describes how Claude Code executes concurrent background work through a unified task system. Five distinct task types -- LocalShellTask, LocalAgentTask, RemoteAgentTask, InProcessTeammateTask, and DreamTask -- each implement a common `Task` interface but differ fundamentally in where and how they run. All tasks register into the same `AppState.tasks` map, persist output to disk, and surface lifecycle events through XML-based notifications.

## Systems Involved

- [Task System](../entities/task-system.md) -- type definitions (`TaskType`, `TaskStatus`, `TaskStateBase`), ID generation, and the `Task` interface
- [State Management](../entities/state-management.md) -- `AppState.tasks` map, `SetAppState` updater, store subscription
- [Agent System](../entities/agent-system.md) -- subagent spawning used by LocalAgentTask and InProcessTeammateTask
- [Permission System](../entities/permission-system.md) -- tool permission gating within agent-type tasks
- [Execution Flow](../concepts/execution-flow.md) -- how tasks fit into the broader REPL query loop
- [Agent Isolation](../concepts/agent-isolation.md) -- worktree and process isolation strategies

## Interaction Model

### Task Lifecycle

Every task follows the same state machine:

```
pending -> running -> completed | failed | killed
```

Terminal states are identified by `isTerminalTaskStatus()`. Once terminal, a task cannot receive new messages, and the framework schedules eviction after `STOPPED_DISPLAY_MS` (3 seconds for killed tasks) or `PANEL_GRACE_MS` (30 seconds for agent tasks in the coordinator panel).

### Task Registration and State Updates

All tasks share a common registration and update pattern:

1. **ID generation** -- `generateTaskId(type)` produces a prefixed 9-character ID (`b` for bash, `a` for agent, `r` for remote, `t` for teammate, `d` for dream) using a cryptographically random suffix.
2. **Base state creation** -- `createTaskStateBase()` initializes common fields including `outputFile` (from `getTaskOutputPath(id)`), `startTime`, `status: 'pending'`, and `notified: false`.
3. **Registration** -- `registerTask(task, setAppState)` inserts the task into `AppState.tasks`.
4. **Updates** -- `updateTaskState<T>(taskId, setAppState, updater)` applies a type-safe transformation. If the updater returns the same reference, the update is a no-op (no re-render).
5. **Notifications** -- Tasks enqueue XML-tagged notification messages via `enqueuePendingNotification()` to inform the model of completion, failure, or stalls.

### Task Type Specifics

**LocalShellTask** (`local_bash`): Spawns a child process via `ShellCommand`. Output is written to a file in the session-scoped task output directory (`<projectTempDir>/<sessionId>/tasks/`). A stall watchdog polls output growth every 5 seconds; if output stalls for 45 seconds and the tail matches interactive prompt patterns (e.g., `(y/n)`, `Continue?`), it fires a notification so the model can intervene. Output files are opened with `O_NOFOLLOW` to prevent symlink attacks from sandboxed processes.

**LocalAgentTask** (`local_agent`): Runs a Claude subagent in a separate async context within the same Node.js process. Tracks progress via `ProgressTracker` (tool use count, token consumption, recent tool activities). The output file is a symlink to the agent's transcript path. Supports both foreground and backgrounded execution modes.

**RemoteAgentTask** (`remote_agent`): Delegates work to a remote Claude Code session via the Teleport API. Polls the remote session for events, parses SDK messages, and tracks completion via pluggable `RemoteTaskCompletionChecker` functions registered per remote task type (remote-agent, ultraplan, ultrareview, autofix-pr, background-pr). Persists metadata to the session sidecar for resume support.

**InProcessTeammateTask** (`in_process_teammate`): Runs a teammate agent in the same Node.js process using `AsyncLocalStorage` for isolation. Unlike LocalAgentTask, teammates have team-aware identity (`agentName@teamName`), support plan mode approval flows, can be idle (waiting for work), and accept injected user messages via a `pendingUserMessages` queue. Messages are capped to prevent unbounded growth.

**DreamTask** (`dream`): Background memory consolidation agent. Tracks phases (`starting` -> `updating`), files touched (from Edit/Write tool-use patterns), and recent assistant turns (capped at 30). On kill, rolls back the consolidation lock mtime so the next session can retry. Dream tasks set `notified: true` immediately since they have no model-facing notification path -- they are UI-only.

### Output Persistence

Task output persists to disk in a session-scoped directory:

```
<projectTempDir>/<sessionId>/tasks/<taskId>
```

- **Bash tasks**: Direct file output with `O_NOFOLLOW` security.
- **Agent tasks**: Symlink to the agent transcript path via `initTaskOutputAsSymlink()`.
- **Output deltas**: `getTaskOutputDelta()` reads new bytes since the last `outputOffset`, enabling incremental notification payloads.
- **Eviction**: `evictTaskOutput()` unlinks the output file when a task is evicted from AppState.
- **Size cap**: `MAX_TASK_OUTPUT_BYTES` (5 GB) enforced via watchdog (bash) or chunk-level dropping (hooks).

### Isolation Boundaries

| Task Type | Process | Memory | Filesystem |
|---|---|---|---|
| LocalShellTask | Child process | Separate | Shared (sandbox-aware) |
| LocalAgentTask | Same process, async | Shared heap | Shared |
| RemoteAgentTask | Remote machine | Fully separate | Fully separate |
| InProcessTeammateTask | Same process, AsyncLocalStorage | Shared heap | Shared or worktree |
| DreamTask | Forked agent | Separate | Shared |

### Stopping Tasks

The `stopTask()` function in `tasks/stopTask.ts` provides a unified interface used by both the TaskStopTool (model-invoked) and SDK control requests. It looks up the task by ID, validates it is running, dispatches to the task-type-specific `kill()` method, and optionally suppresses the XML notification for bash tasks (where the "exit code 137" message is noise rather than useful information).

## Key Interfaces

```typescript
// The polymorphic task interface -- only kill is dispatched polymorphically
type Task = {
  name: string
  type: TaskType
  kill(taskId: string, setAppState: SetAppState): Promise<void>
}

// Shared base for all concrete task states in AppState.tasks
type TaskStateBase = {
  id: string
  type: TaskType
  status: TaskStatus
  description: string
  toolUseId?: string
  startTime: number
  endTime?: number
  outputFile: string
  outputOffset: number
  notified: boolean
}

// Context passed to task spawn functions
type TaskContext = {
  abortController: AbortController
  getAppState: () => AppState
  setAppState: SetAppState
}

// Union of all concrete task states
type TaskState =
  | LocalShellTaskState
  | LocalAgentTaskState
  | RemoteAgentTaskState
  | InProcessTeammateTaskState
  | LocalWorkflowTaskState
  | MonitorMcpTaskState
  | DreamTaskState

// Framework utilities
function registerTask(task: TaskState, setAppState: SetAppState): void
function updateTaskState<T>(taskId: string, setAppState: SetAppState, updater: (task: T) => T): void
function generateTaskId(type: TaskType): string
function isTerminalTaskStatus(status: TaskStatus): boolean
```

## See Also

- [Task System](../entities/task-system.md) -- core type definitions and registry
- [State Management](../entities/state-management.md) -- AppState store and context
- [Agent System](../entities/agent-system.md) -- subagent spawning and agent definitions
- [Agent Isolation](../concepts/agent-isolation.md) -- worktree and process-level isolation
- [Execution Flow](../concepts/execution-flow.md) -- how tasks integrate with the REPL loop
- [Permission Model](../concepts/permission-model.md) -- how tasks interact with permission gating
- [Hook System](../concepts/hook-system.md) -- hooks that fire on task lifecycle events
