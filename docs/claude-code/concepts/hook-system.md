# Hook System

## Overview

Claude Code has two distinct "hook" concepts that share the name but serve different purposes:

1. **React-style hooks** -- Custom React hooks (`use*` functions) that compose UI state, side effects, and business logic in the terminal-based Ink application. These follow standard React patterns.

2. **Frontmatter hooks (settings hooks)** -- User-defined shell commands, HTTP endpoints, agent hooks, or callback functions that execute at specific lifecycle events (PreToolUse, PostToolUse, SessionStart, etc.). These are configured in `settings.json` under the `hooks` key.

Both systems are central to Claude Code's extensibility. React hooks let internal modules compose cleanly; frontmatter hooks let users and enterprises inject custom behavior at well-defined lifecycle points.

## Mechanism

### React-Style Hooks

The `hooks/` directory contains dozens of React hooks that power the REPL. Key categories:

#### Tool Permission Pipeline

The permission pipeline is the most complex hook composition in the system:

- **`useCanUseTool`** -- The central permission gate. Given a tool, input, and context, it resolves whether the tool use is allowed, denied, or needs to ask the user. The pipeline:
  1. Check if the request is aborted.
  2. Call `hasPermissionsToUseTool()` against the merged permission rules.
  3. If allowed by config, resolve immediately.
  4. If denied, record the denial and resolve.
  5. If "ask", enter the interactive handler pipeline:
     - Run `handleCoordinatorPermission` (for coordinator/swarm modes).
     - Run `handleSwarmWorkerPermission` (for swarm workers).
     - Run `handleInteractivePermission` (standard interactive prompt to the user).
  6. At each stage, frontmatter hooks (`PermissionRequest` event) may intercept and approve or deny.

- **`PermissionContext`** (`hooks/toolPermission/PermissionContext.ts`) -- A frozen context object created per tool-use request. Encapsulates the tool, input, abort signal, queue operations, and helpers for logging decisions, running hooks, building allow/deny responses, and persisting permission updates.

#### Settings and Tools Composition

- **`useSettings`** -- Returns `ReadonlySettings` from `AppState`, reactively updating when settings files change on disk via the change detector.
- **`useMergedTools`** -- Assembles the full tool pool by combining built-in tools with MCP tools, applying deny rules, deduplicating, and merging with initial tools. Uses `assembleToolPool()` (shared with `runAgent`).
- **`useMergedCommands`** / **`useMergedClients`** -- Similar composition patterns for slash commands and API clients.

#### Session Lifecycle Hooks

- **`useSessionBackgrounding`** -- Manages session background/foreground transitions.
- **`useFileHistorySnapshotInit`** -- Initializes file history tracking.
- **`useSwarmInitialization`** -- Sets up swarm mode infrastructure.
- **`useDynamicConfig`** -- Polls for dynamic configuration updates.
- **`useExitOnCtrlCD`** / **`useExitOnCtrlCDWithKeybindings`** -- Handle graceful exit sequences.

### Frontmatter Hooks (Settings Hooks)

Configured under the `hooks` key in any settings source, frontmatter hooks fire at lifecycle events. The system supports multiple hook types and matching strategies.

#### Hook Events

The full set of hook events defined in `types/hooks.ts` and `entrypoints/agentSdkTypes.ts`:

| Event | Timing | Key Use Case |
|-------|--------|-------------|
| `PreToolUse` | Before a tool executes | Validate/modify tool input, approve/block |
| `PostToolUse` | After successful tool execution | Log, transform output, inject context |
| `PostToolUseFailure` | After tool execution fails | Error recovery, logging |
| `PermissionRequest` | When permission prompt would appear | Automated approval/denial |
| `PermissionDenied` | After permission is denied | Retry logic |
| `UserPromptSubmit` | When user submits a prompt | Input validation, context injection |
| `SessionStart` | Session initialization | Environment setup, watch paths |
| `SessionEnd` | Session teardown (1.5s timeout default) | Cleanup, reporting |
| `Stop` | When assistant stops generating | Post-generation actions |
| `SubagentStart` | Subagent spawned | Subagent configuration |
| `SubagentStop` | Subagent completes | Result processing |
| `Notification` | System notification | External alerting |
| `PreCompact` / `PostCompact` | Around context compaction | Custom compaction behavior |
| `TeammateIdle` | Teammate becomes idle | Workflow orchestration |
| `TaskCreated` / `TaskCompleted` | Task lifecycle | Task tracking |
| `FileChanged` / `CwdChanged` | Filesystem events | Reactive tooling |
| `ConfigChange` | Settings file changed | Dynamic reconfiguration |
| `Setup` | First-time setup | Environment bootstrapping |

#### Hook Types

Each hook matcher can specify commands of different types:

- **Shell command hooks** (`type: "command"` or bare `command` string) -- Execute a shell command. Output is parsed as JSON if it starts with `{`; otherwise treated as plain text.
- **HTTP hooks** (`type: "http"`) -- POST to an HTTP endpoint with the hook input as JSON body.
- **Agent hooks** (`type: "agent"`) -- Spawn a Claude agent (via `execAgentHook`) that receives the hook input as its prompt.
- **Prompt hooks** (`type: "prompt"`) -- Send the hook input to a model query.
- **Callback hooks** (internal/plugin) -- TypeScript functions registered via `HookCallback`. Plugins and internal systems use these.

#### Hook Matching

Hook matchers determine which hooks fire for a given event. Each event in the `hooks` settings contains an array of matchers:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "BashTool", "hooks": [{ "command": "./validate-bash.sh" }] },
      { "hooks": [{ "type": "http", "url": "https://audit.example.com/hook" }] }
    ]
  }
}
```

- If `matcher` is set, the hook only fires when the tool name matches.
- If `matcher` is omitted, the hook fires for all tool uses of that event type.
- Plugin hooks use `pluginName` to identify their source.

#### Hook Output Protocol

Command hooks communicate back via JSON on stdout:

- **Sync response**: `{ "continue": true/false, "decision": "approve"/"block", "reason": "...", "hookSpecificOutput": { ... } }`
- **Async response**: `{ "async": true, "asyncTimeout": 30 }` -- hook continues running in background; registered in `AsyncHookRegistry`.
- **Plain text**: Non-JSON stdout is captured as a message.

`PreToolUse` hooks can return `permissionDecision` ("allow"/"deny"/"ask") and `updatedInput` to modify tool inputs before execution.

#### Hook Execution and Trust

All hooks require workspace trust as a defense-in-depth measure (`shouldSkipHookDueToTrust()`). In non-interactive (SDK) mode, trust is implicit.

Hooks have a 10-minute default timeout (`TOOL_HOOK_EXECUTION_TIMEOUT_MS`), except `SessionEnd` hooks which get 1.5 seconds (`SESSION_END_HOOK_TIMEOUT_MS_DEFAULT`, overridable via `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`).

Managed-only mode (`shouldAllowManagedHooksOnly`) can restrict hooks to those from policy settings only, preventing project-level hook injection.

## Involved Entities

- [Tool System](../entities/tool-system.md) -- tools are gated by the permission hook pipeline
- [Permission System](../entities/permission-system.md) -- `useCanUseTool` is the bridge between permissions and hooks
- [Plugin System](../entities/plugin-system.md) -- plugins register callback hooks
- [Agent System](../entities/agent-system.md) -- agent hooks spawn sub-agents
- [Configuration System](../entities/configuration-system.md) -- hooks are configured in settings.json
- [State Management](../entities/state-management.md) -- `useSettings` reads from AppState

## Source Evidence

| File | Role |
|------|------|
| `hooks/useCanUseTool.tsx` | Central permission decision hook, orchestrates the full allow/deny/ask pipeline |
| `hooks/toolPermission/PermissionContext.ts` | Frozen per-request context with hook execution, queue ops, decision builders |
| `hooks/toolPermission/handlers/interactiveHandler.ts` | Interactive permission prompt handler |
| `hooks/toolPermission/handlers/coordinatorHandler.ts` | Coordinator-mode permission handler |
| `hooks/useSettings.ts` | Reactive settings hook from AppState |
| `hooks/useMergedTools.ts` | Tool pool assembly via `assembleToolPool()` |
| `utils/hooks.ts` | Core frontmatter hook execution engine: `executeInBackground`, `parseHookOutput`, `createBaseHookInput`, trust checks |
| `types/hooks.ts` | Hook type definitions, Zod schemas for hook JSON output, `HookCallback` type |
| `utils/hooks/AsyncHookRegistry.ts` | Registry for background async hooks |
| `utils/hooks/execAgentHook.ts` | Agent-type hook executor |
| `utils/hooks/execHttpHook.ts` | HTTP-type hook executor |
| `utils/hooks/hooksConfigSnapshot.ts` | Snapshot capture and managed-only restriction |
| `services/tools/toolHooks.ts` | Tool-level hook orchestration |

## See Also

- [Settings Hierarchy](./settings-hierarchy.md) -- hooks are configured within the settings system
- [Error Handling Patterns](./error-handling-patterns.md) -- hook blocking errors and cancellation
- [Permission System](../entities/permission-system.md) -- permission rules that hooks can override
- [Tool System](../entities/tool-system.md) -- tools that hooks gate and modify
