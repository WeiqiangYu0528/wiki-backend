# State-Driven Rendering

## Overview

This synthesis describes how Claude Code's terminal UI renders in response to state changes. The application uses a custom fork of Ink (a React renderer for terminals) that produces frames written to stdout. All UI state flows through a single `AppState` object managed by a custom store with `useSyncExternalStore` integration. Components consume state via selectors, and user input is routed through a keybinding system that maps keystrokes to named actions.

## Systems Involved

- [State Management](../entities/state-management.md) -- `AppState`, `AppStateStore`, `createStore()`
- [Tool System](../entities/tool-system.md) -- tool permission context drives permission UI
- [Task System](../entities/task-system.md) -- `AppState.tasks` drives task pills and panels
- [Agent System](../entities/agent-system.md) -- agent state drives teammate views and coordinator panels
- [Permission Model](../concepts/permission-model.md) -- permission mode determines which dialogs appear
- [Session Lifecycle](../concepts/session-lifecycle.md) -- state initialization and teardown

## Interaction Model

### The Store Pattern

The state layer is a minimal, custom implementation (not Redux or Zustand):

```
createStore(initialState, onChange?) -> { getState, setState, subscribe }
```

- **`getState()`** returns the current immutable snapshot.
- **`setState(updater)`** applies a functional update. If `Object.is(next, prev)` is true, the update is a no-op -- no listeners fire.
- **`subscribe(listener)`** registers a listener called synchronously on every state change. Returns an unsubscribe function.
- **`onChange`** is an optional callback receiving `{ newState, oldState }`, used for side effects like persisting settings changes to disk via `onChangeAppState`.

The store is created once in `AppStateProvider` and exposed via `AppStoreContext` (a React context). Components access it through:

- **`useAppState(selector)`** -- subscribes to the store via `useSyncExternalStore`, re-rendering only when the selected slice changes.
- **`useSetAppState()`** -- returns the `setState` function for dispatching updates.

### AppState Structure

`AppState` is a deeply immutable type (via `DeepImmutable<>`) with mutable carve-outs for `tasks` (contains function types in `AbortController`), `agentNameRegistry` (a `Map`), and several other fields that use complex types. Key rendering-relevant slices:

| Slice | Drives |
|---|---|
| `tasks` | Task pills in footer, task list dialogs, coordinator panel |
| `mcp.clients` / `mcp.tools` | MCP connection indicators, tool availability |
| `plugins` | Plugin status, error display |
| `toolPermissionContext` | Permission request dialogs, mode indicators |
| `viewingAgentTaskId` | Which agent's transcript is displayed |
| `viewSelectionMode` | Agent selection UI state |
| `expandedView` | Task/teammate expanded panel visibility |
| `footerSelection` | Which footer pill has keyboard focus |
| `statusLineText` | Status bar content |
| `thinkingEnabled` | Thinking toggle indicator |
| `promptSuggestion` | Autocomplete suggestion overlay |
| `speculation` | Speculative execution state |
| `notifications` | Toast notification queue |
| `inbox` | Swarm message inbox |
| `tungstenActiveSession` | Tmux panel state |
| `bagelActive` / `bagelUrl` | WebBrowser tool panel |

### Selectors

Selectors are pure functions that derive computed state from `AppState`. They live in `state/selectors.ts` and follow a convention of accepting a `Pick<AppState, ...>` parameter for testability:

- **`getViewedTeammateTask(appState)`** -- returns the `InProcessTeammateTaskState` for the currently viewed teammate, or `undefined` if viewing the leader.
- **`getActiveAgentForInput(appState)`** -- determines where user input should be routed: `{ type: 'leader' }`, `{ type: 'viewed', task }` (in-process teammate), or `{ type: 'named_agent', task }` (background agent). This selector drives the input routing logic in the REPL.

Additional derived state (e.g., `isBackgroundTask()` in `tasks/types.ts`) acts as a selector-like filter, determining which tasks appear in the background indicator.

### The Ink Rendering Engine

Claude Code ships a heavily customized Ink fork (`src/ink/`) that is a full React-to-terminal renderer:

**Reconciler**: Uses `react-reconciler` with `ConcurrentRoot` mode. The reconciler manages a virtual DOM of terminal nodes, diffs them, and produces frames.

**Frame pipeline**:
1. React commits produce a tree of layout nodes.
2. Yoga (CSS flexbox engine) computes layout dimensions.
3. `renderNodeToOutput()` converts the laid-out tree into a character grid (`Screen`).
4. The `optimizer` diffs the new screen against the previous screen.
5. `writeDiffToTerminal()` emits only the changed cells as ANSI escape sequences.

**Screen model**: The screen is a 2D grid of cells, each with character content, style (via `StylePool`), and optional hyperlink (via `HyperlinkPool`). Cell width handling accounts for full-width CJK characters, emoji, and bidirectional text.

**Alt-screen mode**: The renderer operates in the terminal's alternate screen buffer (`ENTER_ALT_SCREEN` / `EXIT_ALT_SCREEN`), providing full-screen rendering without polluting scrollback.

**Frame timing**: Frames are throttled to `FRAME_INTERVAL_MS`. The renderer tracks Yoga layout time, React commit time, and diff time for performance diagnostics.

**Mouse and focus**: The engine supports mouse tracking (`ENABLE_MOUSE_TRACKING`), hit testing (`dispatchClick`, `dispatchHover`), text selection (`SelectionState`), and focus management (`FocusManager`).

### Component Architecture

The component tree, rooted in the REPL screen (`screens/REPL.tsx`), is structured as:

```
AppStateProvider
  MailboxProvider
    VoiceProvider
      KeybindingProvider
        REPL
          Messages / VirtualMessageList
          PermissionRequest
          PromptInput
          TaskListV2 / CoordinatorAgentStatus
          TeammateViewHeader
          StatusLine / StatusNotices
          Various Dialogs (CostThreshold, IdleReturn, etc.)
```

**Message rendering**: The `Messages` component renders the conversation as a virtualized list (`VirtualMessageList`). Each message is wrapped in `MessageRow` with timestamp, model indicator, and response content. Tool use blocks render with specialized components (`FileEditToolDiff`, `BashModeProgress`, `ToolUseLoader`, etc.).

**Permission rendering**: `PermissionRequest` consumes `AppState.toolPermissionContext` to display approval dialogs. The component handles tool use confirmation queues, with support for keyboard-driven approval (y/n) and session-level "always allow" rules.

**Task rendering**: `TaskListV2` renders running background tasks as pills in the footer area. The `CoordinatorAgentStatus` component shows agent progress for LocalAgentTask instances. Shift+Down opens the expanded task dialog.

### Keybinding System

The keybinding system (`src/keybindings/`) provides a declarative, context-aware key mapping:

**Binding resolution**: `KeybindingProvider` wraps the app and exposes a `resolve(input, key, activeContexts)` function. Each keystroke is matched against bindings filtered by the currently active contexts (e.g., `prompt`, `dialog`, `transcript`).

**Chord support**: Multi-key sequences (e.g., `ctrl+k ctrl+c`) are supported. The resolver maintains `pendingChord` state -- if a partial chord is detected, it waits for the next keystroke before resolving.

**Context priority**: When multiple bindings match, the binding from the highest-priority active context wins. Components register/unregister their context on mount/unmount via `registerActiveContext` / `unregisterActiveContext`.

**Handler dispatch**: `useKeybinding(action, context, handler)` registers a handler for a named action within a context. When the keybinding resolver matches an action, `invokeAction(action)` calls all registered handlers.

**User customization**: Default bindings (`defaultBindings.ts`) are merged with user bindings from `~/.claude/keybindings.json` (`loadUserBindings.ts`). User bindings override defaults for the same action+context pair.

### Settings Reactivity

The `AppStateProvider` subscribes to settings file changes via `useSettingsChange()`. When settings files change on disk, `applySettingsChange(source, setState)` updates `AppState.settings`, which cascades to all components that depend on settings-derived state (permission mode, model selection, tool availability, etc.).

## Key Interfaces

```typescript
// The store
type Store<T> = {
  getState: () => T
  setState: (updater: (prev: T) => T) => void
  subscribe: (listener: () => void) => () => void
}

// Store context (React)
const AppStoreContext: React.Context<AppStateStore | null>

// State access hooks
function useAppState<T>(selector: (state: AppState) => T): T
function useSetAppState(): (updater: (prev: AppState) => AppState) => void

// Selectors
function getViewedTeammateTask(
  appState: Pick<AppState, 'viewingAgentTaskId' | 'tasks'>
): InProcessTeammateTaskState | undefined

type ActiveAgentForInput =
  | { type: 'leader' }
  | { type: 'viewed'; task: InProcessTeammateTaskState }
  | { type: 'named_agent'; task: LocalAgentTaskState }

function getActiveAgentForInput(appState: AppState): ActiveAgentForInput

// Keybinding system
type KeybindingContextValue = {
  resolve: (input: string, key: Key, activeContexts: KeybindingContextName[]) => ChordResolveResult
  setPendingChord: (pending: ParsedKeystroke[] | null) => void
  getDisplayText: (action: string, context: KeybindingContextName) => string | undefined
  bindings: ParsedBinding[]
  pendingChord: ParsedKeystroke[] | null
  activeContexts: Set<KeybindingContextName>
  registerActiveContext: (context: KeybindingContextName) => void
  unregisterActiveContext: (context: KeybindingContextName) => void
  registerHandler: (registration: HandlerRegistration) => () => void
  invokeAction: (action: string) => boolean
}
```

## See Also

- [State Management](../entities/state-management.md) -- AppState definition and store implementation
- [Task System](../entities/task-system.md) -- task states rendered in the UI
- [Agent System](../entities/agent-system.md) -- agent views and coordinator panel
- [Permission Model](../concepts/permission-model.md) -- permission dialogs and approval flows
- [Session Lifecycle](../concepts/session-lifecycle.md) -- state initialization on session start
- [Task Execution and Isolation](./task-execution-and-isolation.md) -- how tasks produce state that drives rendering
- [Configuration Resolution Chain](./configuration-resolution-chain.md) -- settings reactivity
