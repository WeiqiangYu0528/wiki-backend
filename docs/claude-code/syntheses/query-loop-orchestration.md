# Query Loop Orchestration

## Overview

This synthesis describes how the main query loop operates -- the state machine that drives every conversation turn in Claude Code. The loop coordinates API calls, streaming response parsing, tool execution (with parallel batching), permission checking, context compaction, and budget enforcement. Both the interactive REPL and the headless SDK path converge on the same `query()` generator function.

## Systems Involved

- [Query Engine](../entities/query-engine.md) -- `QueryEngine` class and `submitMessage()` entry point
- [Tool System](../entities/tool-system.md) -- tool dispatch, `runTools()` orchestration, `StreamingToolExecutor`
- [Permission System](../entities/permission-system.md) -- `canUseTool` callback invoked per tool call
- [Agent System](../entities/agent-system.md) -- subagent loops enter `query()` recursively
- [State Management](../entities/state-management.md) -- `AppState`, `ToolUseContext`, mutable loop state

## Interaction Model

### Entry Points

There are two paths into the query loop:

1. **REPL (interactive)**: The React-based UI calls `query()` directly, wiring up `canUseTool` from `useCanUseTool()` which can display permission prompts to the user.
2. **SDK/Headless**: `QueryEngine.submitMessage()` prepares the system prompt, processes user input, then calls `query()`. Permission denials are tracked for SDK reporting.

Both paths produce the same `AsyncGenerator<StreamEvent | Message>`.

### The State Machine

```
                    +-------------------+
                    |   Loop Entry      |
                    | (while true)      |
                    +--------+----------+
                             |
                    +--------v----------+
                    | Pre-API Phase     |
                    | - snip compact    |
                    | - microcompact    |
                    | - context collapse|
                    | - autocompact     |
                    | - budget check    |
                    +--------+----------+
                             |
                    +--------v----------+
                    | API Streaming     |
                    | callModel()       |
                    | - yield assistant |
                    |   messages        |
                    | - collect tool_use|
                    |   blocks          |
                    | - streaming tool  |
                    |   execution       |
                    +--------+----------+
                             |
              +--------------+--------------+
              |                             |
     +--------v--------+          +--------v--------+
     | No tool_use      |          | Has tool_use    |
     | blocks            |          | blocks          |
     +--------+--------+          +--------+--------+
              |                             |
     +--------v--------+          +--------v--------+
     | Stop Hooks       |          | Tool Execution  |
     | - PostToolUse    |          | - permission    |
     | - check result   |          |   check         |
     +--------+--------+          | - runTools()    |
              |                    | - yield results |
     +--------v--------+          +--------+--------+
     | TERMINAL         |                   |
     | Return reason    |          +--------v--------+
     +------------------+          | Post-Tool Phase |
                                   | - attachments   |
                                   | - memory inject |
                                   | - skill discover|
                                   | - cmd queue     |
                                   +--------+--------+
                                            |
                                   +--------v--------+
                                   | CONTINUE        |
                                   | state = {...}   |
                                   | -> Loop Entry   |
                                   +-----------------+
```

### Phase 1: Pre-API Processing

Each iteration begins with context management:

1. **Tool result budget** (`applyToolResultBudget`): Large tool results that were persisted to disk are replaced with file-path references to keep context manageable.
2. **Snip compact** (feature-gated): Removes old conversation segments above a token threshold, yielding a boundary message.
3. **Microcompact**: Compresses tool results within messages (e.g., collapsing verbose search output).
4. **Context collapse** (feature-gated): Projects a collapsed view of archived conversation segments.
5. **Autocompact**: If the context exceeds a threshold, runs a compaction side-query that summarizes earlier conversation into a compact boundary. Tracks `AutoCompactTrackingState` with turn counters and consecutive failure counts.
6. **Blocking limit check**: If autocompact is disabled, checks whether the context exceeds the hard token limit and returns a terminal error if so.

### Phase 2: API Streaming

The loop calls `callModel()` (via `deps.callModel`) with the prepared messages, system prompt, and tool definitions. The response streams back as a sequence of events:

- **Assistant messages**: Content blocks (text, thinking, tool_use) are yielded to the caller as they arrive.
- **Tool use blocks**: Accumulated into `toolUseBlocks[]`. When `StreamingToolExecutor` is enabled, tool execution begins speculatively while the API is still streaming.
- **Withholding**: Recoverable errors (prompt-too-long, max-output-tokens, media-size) are withheld from the yield stream so recovery logic can retry before the caller sees a failure.

### Phase 3: Tool Execution

When the assistant response contains `tool_use` blocks, tools are executed:

1. **Partitioning** (`partitionToolCalls` in `toolOrchestration.ts`): Tool calls are grouped into batches. Consecutive concurrency-safe (read-only) tools form parallel batches; non-concurrent tools run serially.
2. **Permission check**: Each tool call goes through `canUseTool()`, which invokes `hasPermissionsToUseTool()` and may prompt the user.
3. **Execution**: `runToolUse()` calls `tool.call()` with the `ToolUseContext` and progress callback.
4. **Result injection**: Tool results are yielded as `UserMessage` blocks with `tool_result` content, then appended to the message array for the next API call.
5. **Context modification**: Non-concurrent tools may return a `contextModifier` that updates the `ToolUseContext` for subsequent tools.

Parallel execution respects a configurable concurrency limit (`CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY`, default 10).

### Phase 4: Post-Tool Processing

After tools execute:

1. **Attachment injection**: Memory files (`CLAUDE.md`), relevant context, and skill discovery results are attached.
2. **Command queue**: Queued slash commands (from the message queue) are consumed and injected.
3. **Post-sampling hooks**: `executePostSamplingHooks()` runs any registered post-sampling hook functions.
4. **Token budget check** (feature-gated): If the `TOKEN_BUDGET` feature is enabled, `checkTokenBudget()` determines whether to auto-continue or stop.
5. **Stop hooks**: `handleStopHooks()` checks whether post-tool-use hooks want to force continuation.

### Phase 5: Continue or Terminate

The loop either continues (when tool calls produced results that need a follow-up API call) or terminates. Terminal conditions:

- No `tool_use` blocks in the response (model is done)
- `maxTurns` reached
- Budget exhausted
- Abort signal fired
- Blocking token limit hit
- Unrecoverable API error

### Mutable Loop State

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

State is carried between iterations as a single object. Each continue site writes `state = { ...state, ...updates }` to advance to the next iteration.

### Streaming Tool Execution

When the `streamingToolExecution` gate is enabled, a `StreamingToolExecutor` starts permission checks and tool execution as soon as each `tool_use` block finishes streaming -- before the full API response completes. Completed results are drained from the executor and yielded interleaved with the streaming response. If a model fallback occurs mid-stream, the executor is discarded and recreated to prevent orphan results.

## Key Interfaces

### query() Signature (`src/query.ts`)

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
  maxTurns?: number
  taskBudget?: { total: number }
}

function query(params: QueryParams): AsyncGenerator<StreamEvent | Message, Terminal>
```

### ToolUseContext (`src/Tool.ts`)

The per-conversation context threaded through every tool call:

```typescript
type ToolUseContext = {
  options: {
    tools: Tools
    commands: Command[]
    mainLoopModel: string
    mcpClients: MCPServerConnection[]
    thinkingConfig: ThinkingConfig
    agentDefinitions: AgentDefinitionsResult
    maxBudgetUsd?: number
    refreshTools?: () => Tools
  }
  abortController: AbortController
  readFileState: FileStateCache
  messages: Message[]
  getAppState(): AppState
  setAppState(f: (prev: AppState) => AppState): void
  queryTracking?: QueryChainTracking
  agentId?: AgentId
  // ... many more fields
}
```

### runTools() (`src/services/tools/toolOrchestration.ts`)

```typescript
function runTools(
  toolUseMessages: ToolUseBlock[],
  assistantMessages: AssistantMessage[],
  canUseTool: CanUseToolFn,
  toolUseContext: ToolUseContext,
): AsyncGenerator<MessageUpdate, void>
```

### QueryEngine.submitMessage() (`src/QueryEngine.ts`)

```typescript
class QueryEngine {
  async *submitMessage(
    prompt: string | ContentBlockParam[],
    options?: { uuid?: string; isMeta?: boolean },
  ): AsyncGenerator<SDKMessage, void, unknown>
}
```

## See Also

- [Query Engine](../entities/query-engine.md) -- the `QueryEngine` class and session management
- [Tool System](../entities/tool-system.md) -- tool definitions and the `Tool` interface
- [Permission System](../entities/permission-system.md) -- `canUseTool` and permission checking
- [State Management](../entities/state-management.md) -- `AppState` and `ToolUseContext`
- [Agent-Tool-Skill Triad](./agent-tool-skill-triad.md) -- how agents and skills enter the query loop recursively
- [Permission Enforcement Pipeline](./permission-enforcement-pipeline.md) -- the full permission check sequence within each tool call
