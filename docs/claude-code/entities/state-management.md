# State Management

## Overview

Central state management for Claude Code. `AppState` is the single source of truth managing everything from tasks and tool permissions to MCP connections, plugins, bridge state, speculation, UI controls, and team coordination. The system uses a minimal Zustand-like external store pattern -- a plain closure with `getState`/`setState`/`subscribe` -- integrated with React via context and `useSyncExternalStore`. Components select narrow slices of state through selector functions, and re-render only when the selected value changes (compared via `Object.is`). A global `onChangeAppState` callback handles side effects like persisting settings, syncing permission modes to CCR, and clearing credential caches.

## Key Types

### Store<T>

The generic store interface, defined in `state/store.ts`:

```ts
type Store<T> = {
  getState: () => T
  setState: (updater: (prev: T) => T) => void
  subscribe: (listener: Listener) => () => void
}
```

`setState` accepts an updater function (not a partial object). If the updater returns the same reference (`Object.is(next, prev)`), the update is skipped entirely -- no listeners fire. This makes identity-preserving updates free.

### AppStateStore

A type alias for `Store<AppState>`, exported from `state/AppStateStore.ts`.

### AppState

The root state type, wrapped in `DeepImmutable<...>` for the majority of its fields (with explicit exceptions for fields containing function types like `tasks` and `mcp`). Major field groups:

```ts
export type AppState = DeepImmutable<{
  // --- Settings & Model ---
  settings: SettingsJson
  verbose: boolean
  mainLoopModel: ModelSetting          // alias/full name or null (default)
  mainLoopModelForSession: ModelSetting
  effortValue?: EffortValue
  thinkingEnabled: boolean | undefined
  fastMode?: boolean
  advisorModel?: string

  // --- UI State ---
  expandedView: 'none' | 'tasks' | 'teammates'
  isBriefOnly: boolean
  statusLineText: string | undefined
  footerSelection: FooterItem | null
  activeOverlays: ReadonlySet<string>
  coordinatorTaskIndex: number
  viewSelectionMode: 'none' | 'selecting-agent' | 'viewing-agent'

  // --- Permissions ---
  toolPermissionContext: ToolPermissionContext   // includes mode: PermissionMode
  denialTracking?: DenialTrackingState

  // --- Bridge (always-on remote control) ---
  replBridgeEnabled: boolean
  replBridgeConnected: boolean
  replBridgeSessionActive: boolean
  replBridgeReconnecting: boolean
  replBridgeConnectUrl: string | undefined
  replBridgeSessionUrl: string | undefined
  replBridgeEnvironmentId: string | undefined
  replBridgeSessionId: string | undefined
  replBridgeError: string | undefined
  // ... plus several more bridge fields

  // --- Remote / Assistant Mode ---
  kairosEnabled: boolean
  remoteSessionUrl: string | undefined
  remoteConnectionStatus: 'connecting' | 'connected' | 'reconnecting' | 'disconnected'
  remoteBackgroundTaskCount: number
}> & {
  // --- Tasks (mutable, contains function types) ---
  tasks: { [taskId: string]: TaskState }
  agentNameRegistry: Map<string, AgentId>
  foregroundedTaskId?: string
  viewingAgentTaskId?: string

  // --- MCP ---
  mcp: {
    clients: MCPServerConnection[]
    tools: Tool[]
    commands: Command[]
    resources: Record<string, ServerResource[]>
    pluginReconnectKey: number
  }

  // --- Plugins ---
  plugins: {
    enabled: LoadedPlugin[]
    disabled: LoadedPlugin[]
    commands: Command[]
    errors: PluginError[]
    installationStatus: { marketplaces: [...]; plugins: [...] }
    needsRefresh: boolean
  }

  // --- Speculation ---
  speculation: SpeculationState           // 'idle' | 'active' with abort, boundary, etc.
  speculationSessionTimeSavedMs: number
  promptSuggestion: { text; promptId; shownAt; acceptedAt; generationRequestId }
  promptSuggestionEnabled: boolean

  // --- Team / Swarm ---
  teamContext?: { teamName; teammates; leadAgentId; selfAgentId; ... }
  inbox: { messages: Array<{ id; from; text; timestamp; status; ... }> }
  workerSandboxPermissions: { queue: [...]; selectedIndex: number }

  // --- File History & Attribution ---
  fileHistory: FileHistoryState
  attribution: AttributionState
  todos: { [agentId: string]: TodoList }

  // --- Notifications & Elicitation ---
  notifications: { current: Notification | null; queue: Notification[] }
  elicitation: { queue: ElicitationRequestEvent[] }

  // --- Session ---
  authVersion: number
  initialMessage: { message: UserMessage; clearContext?; mode?; allowedPrompts? } | null
  sessionHooks: SessionHooksState
  agentDefinitions: AgentDefinitionsResult

  // ... plus tmux (tungsten), WebBrowser (bagel), computer-use MCP,
  //     REPL context, ultraplan, skill improvement, and companion fields
}
```

### SpeculationState

Tracks speculative execution -- the system that pre-runs tool calls before the user confirms:

```ts
type SpeculationState =
  | { status: 'idle' }
  | {
      status: 'active'
      id: string
      abort: () => void
      startTime: number
      messagesRef: { current: Message[] }
      writtenPathsRef: { current: Set<string> }
      boundary: CompletionBoundary | null
      suggestionLength: number
      toolUseCount: number
      isPipelined: boolean
      // ...
    }
```

### CompletionBoundary

Discriminated union describing what ended a speculative run:

```ts
type CompletionBoundary =
  | { type: 'complete'; completedAt: number; outputTokens: number }
  | { type: 'bash'; command: string; completedAt: number }
  | { type: 'edit'; toolName: string; filePath: string; completedAt: number }
  | { type: 'denied_tool'; toolName: string; detail: string; completedAt: number }
```

## Architecture

### Store Pattern

The store is a minimal closure-based implementation in `state/store.ts` -- roughly 30 lines of code. It mirrors Zustand's core API without the middleware system:

1. `createStore(initialState, onChange?)` returns `{ getState, setState, subscribe }`.
2. `setState` takes an updater function `(prev: T) => T`. If `Object.is(next, prev)` is true, the update is a no-op.
3. On state change, the optional `onChange` callback fires first (for side effects), then all subscribed listeners are notified.
4. `subscribe` returns an unsubscribe function. Listeners are stored in a `Set<Listener>`.

### React Integration

`AppStateProvider` (in `state/AppState.tsx`) creates the store once via `useState(() => createStore(...))` and exposes it through `AppStoreContext`. Key hooks:

- **`useAppState(selector)`** -- the primary read hook. Uses `useSyncExternalStore` under the hood, so React handles subscription lifecycle and concurrent-mode safety. The selector extracts a slice; re-renders fire only when the slice changes by `Object.is`.
- **`useSetAppState()`** -- returns `store.setState` directly. Components that only write state never re-render from state changes. The reference is stable.
- **`useAppStateStore()`** -- returns the full store object, for passing to non-React code.
- **`useAppStateMaybeOutsideOfProvider(selector)`** -- safe version that returns `undefined` when no provider is present, using a `NOOP_SUBSCRIBE` fallback.

The provider also nests `MailboxProvider` and `VoiceProvider` (ant-only, DCE'd in external builds) inside the store context, and wires up settings file watching via `useSettingsChange`.

### Selector Discipline

Selectors must return existing sub-object references, not new objects. Since comparison is `Object.is`, constructing a new object in the selector would cause every state change to trigger a re-render:

```ts
// Good -- returns an existing reference
const suggestion = useAppState(s => s.promptSuggestion)

// Good -- primitive value
const verbose = useAppState(s => s.verbose)

// Bad -- new object every time
const bad = useAppState(s => ({ a: s.verbose, b: s.fastMode }))
```

For multi-field reads, call the hook multiple times with separate selectors rather than combining into one object.

The `state/selectors.ts` file provides reusable selector functions for complex derived state, such as `getViewedTeammateTask` (looks up and type-narrows the viewed agent task) and `getActiveAgentForInput` (determines whether user input routes to the leader, a viewed teammate, or a named agent). These accept `AppState` (or a `Pick<>` subset) and return typed discriminated unions.

### Change Listener (onChangeAppState)

The `onChangeAppState` callback in `state/onChangeAppState.ts` is passed to `createStore` and fires on every state transition. It acts as a centralized side-effect dispatcher, diffing `oldState` vs `newState` to trigger external actions:

- **Permission mode sync** -- When `toolPermissionContext.mode` changes, notifies CCR (via `notifySessionMetadataChanged`) and the SDK status stream (via `notifyPermissionModeChanged`). Externalizes internal-only modes (e.g., `bubble` becomes `default`) before sending to CCR, and skips the notify if the external representation did not change.
- **Model persistence** -- When `mainLoopModel` changes, writes to user settings and updates the bootstrap override.
- **Expanded view persistence** -- Persists `expandedView` changes to global config as `showExpandedTodos`/`showSpinnerTree`.
- **Verbose flag persistence** -- Syncs `verbose` to global config.
- **Tmux panel visibility** -- Persists `tungstenPanelVisible` to global config (ant-only).
- **Settings/auth cache clearing** -- When `settings` changes, clears API key helper, AWS, and GCP credential caches. When `settings.env` changes specifically, re-applies config environment variables.

There is also `externalMetadataToAppState`, an inverse mapping that restores `permission_mode` and `is_ultraplan_mode` from CCR external metadata back into `AppState` (used for worker restart recovery).

### Major State Categories

| Category | Fields | Purpose |
|----------|--------|---------|
| Settings & Model | `settings`, `mainLoopModel`, `effortValue`, `thinkingEnabled`, `fastMode` | User preferences, model selection, thinking/effort config |
| UI | `expandedView`, `footerSelection`, `activeOverlays`, `statusLineText`, `isBriefOnly` | Terminal UI layout and overlay management |
| Permissions | `toolPermissionContext`, `denialTracking` | Permission mode (default/plan/auto), bypass flags, denial limits |
| Tasks | `tasks`, `foregroundedTaskId`, `viewingAgentTaskId` | Background agent tasks, subagent tracking |
| MCP | `mcp.clients`, `mcp.tools`, `mcp.commands`, `mcp.resources` | Model Context Protocol server connections and tools |
| Plugins | `plugins.enabled`, `plugins.disabled`, `plugins.errors` | Plugin loading state, commands, installation status |
| Bridge | `replBridge*` fields (~12 fields) | Always-on remote control bridge to claude.ai |
| Speculation | `speculation`, `speculationSessionTimeSavedMs`, `promptSuggestion` | Speculative execution and prompt suggestions |
| Team/Swarm | `teamContext`, `inbox`, `agentNameRegistry`, `workerSandboxPermissions` | Multi-agent coordination, teammate messaging |
| File History | `fileHistory`, `attribution`, `todos` | File change tracking, commit attribution, todo lists |
| Session | `authVersion`, `initialMessage`, `sessionHooks` | Auth state, startup message, hook lifecycle |

## Source Files

| File | Purpose |
|------|---------|
| `state/AppStateStore.ts` | `AppState` type definition, `AppStateStore` alias, `getDefaultAppState()` factory, helper types (`SpeculationState`, `CompletionBoundary`, `FooterItem`) |
| `state/AppState.tsx` | React context provider (`AppStateProvider`), hooks (`useAppState`, `useSetAppState`, `useAppStateStore`, `useAppStateMaybeOutsideOfProvider`), context creation |
| `state/store.ts` | Generic `Store<T>` type and `createStore()` implementation (~30 lines) |
| `state/selectors.ts` | Reusable selector functions (`getViewedTeammateTask`, `getActiveAgentForInput`) with typed return values |
| `state/onChangeAppState.ts` | Centralized change listener: permission mode sync, model/settings persistence, cache invalidation |

## See Also

- [Architecture Overview](../summaries/architecture-overview.md)
- [Query Engine](query-engine.md)
- [Tool System](tool-system.md)
