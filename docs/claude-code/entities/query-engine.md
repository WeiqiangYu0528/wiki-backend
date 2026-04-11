# Query Engine

## Overview

The Query Engine is the central execution loop that processes user queries in Claude Code. Two complementary modules divide responsibility by execution context: `QueryEngine.ts` provides a class-based orchestrator for SDK and headless (non-interactive) sessions, while `query.ts` implements the streaming query loop used by the interactive REPL. Together they manage the full lifecycle of a conversation turn: system prompt assembly, API calls to Claude, streaming response handling, tool call dispatch, result injection, and the loop-until-done pattern that allows Claude to call tools and continue reasoning until a terminal condition is reached.

The separation exists because SDK callers need a stateful object they can call repeatedly (`submitMessage()`), with structured `SDKMessage` events for each lifecycle step, while the REPL needs a generator-based loop that yields raw `Message` and `StreamEvent` objects for the terminal UI to render in real time.

## Key Types

### QueryEngine class (SDK/headless)

```typescript
class QueryEngine {
  constructor(config: QueryEngineConfig)
  async *submitMessage(
    prompt: string | ContentBlockParam[],
    options?: { uuid?: string; isMeta?: boolean }
  ): AsyncGenerator<SDKMessage, void, unknown>
}
```

One `QueryEngine` instance owns an entire conversation. Each `submitMessage()` call starts a new turn within the same session. Internal state -- messages, file cache, usage counters, permission denials -- persists across turns.

### QueryEngineConfig

```typescript
type QueryEngineConfig = {
  cwd: string
  tools: Tools
  commands: Command[]
  mcpClients: MCPServerConnection[]
  agents: AgentDefinition[]
  canUseTool: CanUseToolFn
  getAppState: () => AppState
  setAppState: (f: (prev: AppState) => AppState) => void
  initialMessages?: Message[]
  readFileCache: FileStateCache
  customSystemPrompt?: string
  appendSystemPrompt?: string
  maxTurns?: number
  maxBudgetUsd?: number
  taskBudget?: { total: number }
  jsonSchema?: Record<string, unknown>
  thinkingConfig?: ThinkingConfig
  fallbackModel?: string
  snipReplay?: (msg: Message, store: Message[]) => { messages: Message[]; executed: boolean } | undefined
  // ...additional fields
}
```

### QueryParams (REPL query loop)

```typescript
type QueryParams = {
  messages: Message[]
  systemPrompt: SystemPrompt
  userContext: { [k: string]: string }
  systemContext: { [k: string]: string }
  canUseTool: CanUseToolFn
  toolUseContext: ToolUseContext
  fallbackModel?: string
  querySource: QuerySource
  maxOutputTokensOverride?: number
  maxTurns?: number
  taskBudget?: { total: number }
}
```

### SDKMessage event types

The SDK path yields typed events to callers:
- **`assistant`** -- Model response content blocks (text, tool_use, thinking)
- **`user`** -- User messages and tool results (replayed for acknowledgment)
- **`progress`** -- Tool execution progress updates
- **`attachment`** -- Memory attachments, hook signals, max-turns notifications
- **`system`** -- Compact boundary markers, init messages
- **`stream_event`** -- Raw Anthropic API stream events (message_start, message_delta, content_block_start/stop)
- **`result`** -- Terminal event with success/error status, cost, usage, duration

### ToolUseContext

Defined in `Tool.ts`, this is the shared execution context passed to every tool call within a turn:

```typescript
type ToolUseContext = {
  options: {
    commands: Command[]
    tools: Tools
    mainLoopModel: string
    thinkingConfig: ThinkingConfig
    mcpClients: MCPServerConnection[]
    isNonInteractiveSession: boolean
    agentDefinitions: AgentDefinitionsResult
    maxBudgetUsd?: number
    // ...
  }
  abortController: AbortController
  readFileState: FileStateCache
  getAppState(): AppState
  setAppState(f: (prev: AppState) => AppState): void
  messages: Message[]
  queryTracking?: { chainId: string; depth: number }
  agentId?: string
  // ...
}
```

### Query tracking

Each iteration of the loop increments `queryTracking.depth` and preserves the same `chainId` (a UUID generated at the start of the turn). This provides a stable identifier for analytics and prevents unbounded fork nesting -- subagents inherit the chain but bump depth.

### Loop state (query.ts)

```typescript
type State = {
  messages: Message[]
  toolUseContext: ToolUseContext
  autoCompactTracking: AutoCompactTrackingState | undefined
  maxOutputTokensRecoveryCount: number
  hasAttemptedReactiveCompact: boolean
  maxOutputTokensOverride: number | undefined
  pendingToolUseSummary: Promise<ToolUseSummaryMessage | null> | undefined
  stopHookActive: boolean | undefined
  turnCount: number
  transition: Continue | undefined
}
```

The `State` object is replaced wholesale at each `continue` site rather than mutated field-by-field, making control flow transitions explicit and testable.

## Architecture

### Main loop flow

The core loop in `query.ts` (`queryLoop` generator) follows this sequence on each iteration:

1. **Snip compaction** (feature-gated) -- Trims old history segments based on token thresholds. Yields boundary messages when snipping occurs.

2. **Microcompact** -- Lightweight per-message compaction applied before autocompact. Operates by `tool_use_id` and can use cached results.

3. **Context collapse** (feature-gated) -- Projects a collapsed context view and commits new collapses. Runs before autocompact so that if collapse alone brings context under threshold, full summarization is avoided.

4. **Autocompact** -- If context exceeds the token threshold and auto-compact is enabled, summarizes the conversation history. Yields compact boundary messages. Tracks consecutive failures via a circuit breaker pattern.

5. **Tool result budget enforcement** -- Applies per-message size limits on aggregate tool result content. Persists replacement records for resumable sessions.

6. **Blocking limit check** -- If context still exceeds the hard blocking limit (and auto-compact is off), surfaces an error and returns `{ reason: 'blocking_limit' }`.

7. **API call with streaming** -- Calls `deps.callModel()` with the prepared messages, system prompt, user/system context, thinking config, and tool definitions. Handles streaming fallback (tombstoning orphaned messages from the failed attempt).

8. **Response parsing** -- As assistant messages stream in, extracts `tool_use` blocks and sets `needsFollowUp = true`. Withholds recoverable errors (prompt-too-long, max-output-tokens, media-size) from the yield stream.

9. **Tool execution** -- Either via `StreamingToolExecutor` (starts tool execution while streaming continues) or `runTools()` (batch execution after streaming completes). Tool results are collected as user messages with `tool_result` content blocks.

10. **Recovery paths** -- If the response was a withheld error:
    - **Context collapse drain** -- Commits all staged collapses and retries
    - **Reactive compact** -- Full summarization as fallback
    - **Max output tokens recovery** -- Injects a "resume" meta-message (up to 3 retries) or escalates the token limit

11. **Stop hooks** -- Evaluates post-sampling hooks that can prevent the response from being accepted.

12. **Termination check** -- If `needsFollowUp` is false and no recovery fired, the turn is complete. Returns `{ reason: 'completed' }`.

13. **Attachment injection** -- After tool calls, fetches memory attachments, queued commands, and skill discovery results. These become additional user messages for the next iteration.

14. **Max turns check** -- If `turnCount` exceeds `maxTurns`, yields a `max_turns_reached` attachment and exits.

15. **Loop continuation** -- Writes the new `State` and continues to step 1.

### QueryEngine wrapper (submitMessage)

`QueryEngine.submitMessage()` wraps the `query()` generator with SDK-specific concerns:

1. **System prompt assembly** -- Calls `fetchSystemPromptParts()` with tools, model, MCP clients. Optionally prepends custom system prompt and appends memory mechanics prompt.

2. **User input processing** -- Runs `processUserInput()` to handle slash commands, attachments, model overrides. Determines whether to query the API at all (`shouldQuery` flag).

3. **Transcript persistence** -- Writes user messages to the session transcript before entering the query loop, so sessions are resumable even if killed mid-request.

4. **Permission tracking** -- Wraps `canUseTool` to intercept and record all permission denials as `SDKPermissionDenial` objects.

5. **Message normalization** -- Converts internal `Message` types to `SDKMessage` events. Handles replay of user messages, compact boundaries, progress updates.

6. **Usage accumulation** -- Aggregates token usage from `stream_event` messages (message_start/message_delta) across the entire turn.

7. **Result emission** -- When the query loop terminates, yields a final `result` event containing total cost, duration, usage, permission denials, and stop reason.

## Key Responsibilities

### Permission tracking

`QueryEngine` wraps the caller-provided `canUseTool` function to intercept every permission decision. Denials are collected into `SDKPermissionDenial[]` and included in the final result event, giving SDK callers visibility into what was blocked and why.

### Usage accumulation

Token counts (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`) are accumulated from raw stream events across all API calls within a turn. The `accumulateUsage()` and `updateUsage()` functions from `services/api/claude.js` handle the arithmetic.

### Compaction

Multiple compaction strategies compose in a specific order: snip > microcompact > context collapse > autocompact. Each targets a different granularity:
- **Snip** removes entire old segments by token threshold
- **Microcompact** compresses individual tool results (cached by `tool_use_id`)
- **Context collapse** archives groups of messages into summaries (a read-time projection, not destructive)
- **Autocompact** performs full conversation summarization when other strategies are insufficient

Reactive compact serves as a fallback triggered by API 413 errors after streaming has started.

### Budget enforcement

Two independent budget mechanisms:
- **maxTurns** -- Hard cap on loop iterations. Checked after tool execution; yields a `max_turns_reached` attachment on breach.
- **maxBudgetUsd / taskBudget** -- Dollar-denominated spending limits. `taskBudget` tracks remaining budget across compaction boundaries by subtracting the pre-compact context window from the running total.

### Transcript persistence

The session transcript is written at key points: after user input processing (before query loop entry), after each assistant/user message, and after compaction boundaries. The `recordTranscript()` function is fire-and-forget for assistant messages (to avoid blocking the generator) but awaited for user messages and compact boundaries (to ensure resumability). Eager flushing (`CLAUDE_CODE_EAGER_FLUSH`) forces immediate disk writes for cowork/desktop integrations.

### File state caching

`readFileState` is a `FileStateCache` (LRU cache) that stores file contents read during tool execution. It persists across turns within a `QueryEngine` instance. Subagents receive a clone via `cloneFileStateCache()` to avoid cross-contamination of file state between parent and child agents.

### Streaming tool execution

When the `streamingToolExecution` gate is enabled, `StreamingToolExecutor` starts executing tool calls as soon as their `tool_use` blocks arrive in the stream (before the full response completes). This overlaps tool execution with model streaming for lower latency. `getRemainingResults()` yields any results that were not yet consumed when streaming finishes, followed by the standard `runTools()` path for any blocks that arrived too late for streaming execution.

## Source Files

| File | Purpose |
|------|---------|
| `QueryEngine.ts` | SDK/headless query orchestrator. Class-based, wraps `query()` with session management, transcript persistence, and SDKMessage normalization. |
| `query.ts` | Interactive REPL streaming query loop. Generator-based, owns the while-true loop, compaction pipeline, API calls, tool execution, and recovery paths. |
| `Tool.ts` | Defines `ToolUseContext`, `Tools`, `findToolByName()`, and the tool interface. |
| `query/config.ts` | `buildQueryConfig()` -- snapshots environment/feature gates once at query entry. |
| `query/deps.ts` | `QueryDeps` interface and `productionDeps()` -- injectable dependencies (callModel, autocompact, microcompact, uuid) for testability. |
| `query/transitions.ts` | `Terminal` and `Continue` types -- typed reasons for loop exit/continuation. |
| `query/stopHooks.ts` | `handleStopHooks()` -- post-response hook evaluation. |
| `query/tokenBudget.ts` | `createBudgetTracker()`, `checkTokenBudget()` -- per-turn output token budget tracking. |
| `services/tools/toolOrchestration.ts` | `runTools()` -- batch tool execution with parallel-where-safe dispatch. |
| `services/tools/StreamingToolExecutor.ts` | Streaming tool execution that overlaps with model output. |
| `services/compact/autoCompact.ts` | Autocompact threshold calculation and trigger logic. |
| `services/compact/compact.ts` | `buildPostCompactMessages()` -- constructs post-compaction message array. |
| `utils/processUserInput/processUserInput.ts` | Slash command parsing, attachment handling, model override extraction. |
| `utils/queryContext.ts` | `fetchSystemPromptParts()` -- assembles system prompt from tools, model, and MCP clients. |
| `utils/sessionStorage.ts` | `recordTranscript()`, `flushSessionStorage()` -- session persistence. |

## See Also

- [Tool System](tool-system.md)
- [Permission System](permission-system.md)
- [State Management](state-management.md)
- [Execution Flow](../concepts/execution-flow.md)
- [Query Loop Orchestration](../syntheses/query-loop-orchestration.md)
