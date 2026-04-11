# Request Lifecycle

## Overview

This synthesis describes the end-to-end journey of a user request in Claude Code: from the moment text is submitted, through authentication, context management, model API call, tool execution, analytics, and back to the rendered response. Multiple services collaborate on each turn. Understanding this flow is essential for diagnosing latency issues, debugging tool failures, or understanding how a new service integrates into the system.

## Systems Involved

- [API Service](../entities/api-service.md) — model query execution
- [MCP Service](../entities/mcp-service.md) — external tool server connections
- [Analytics Service](../entities/analytics-service.md) — telemetry at every step
- [Compact Service](../entities/compact-service.md) — context management before each query
- [OAuth Service](../entities/oauth-service.md) — authentication prerequisite

## Interaction Model

### Phase 0: Authentication (Once at Startup)

Before any request can be made, the [OAuth Service](../entities/oauth-service.md) must have completed its PKCE flow and stored tokens. During startup:
1. `OAuthService.startOAuthFlow()` launches the browser, starts the local HTTP listener, and races automatic vs. manual code capture.
2. On success, tokens are persisted to the keychain via `installOAuthTokens()`.
3. The [Analytics Service](../entities/analytics-service.md) logs `tengu_oauth_auth_code_received`.

Subsequent requests use the cached access token. The token is refreshed if expired before the API call in `checkAndRefreshOAuthTokenIfNeeded()`.

### Phase 1: Context Check (Every Turn)

Before each model query, the query loop calls `autoCompactIfNeeded()` from the [Compact Service](../entities/compact-service.md):

```
messages array (n tokens)
        ↓
calculateTokenWarningState()
        ↓
  above threshold?
    YES → trySessionMemoryCompaction() → success? return compacted messages
              ↓ failed
          compactConversation() via forked agent
              ↓
          messages replaced with summary + boundary marker
    NO  → continue with current messages
```

The [Analytics Service](../entities/analytics-service.md) logs the compaction event and outcome. The [Context Window Management](../concepts/context-window-management.md) concept governs the threshold logic.

### Phase 2: API Call

The query loop calls the [API Service](../entities/api-service.md)'s `query()` function:

1. **Assembly**: Tool schemas are serialized from all available tools (built-in + MCP tools from the [MCP Service](../entities/mcp-service.md)) via `toolToAPISchema()`. Beta flags are merged. The system prompt is assembled with cache scope markers.
2. **Request**: The Anthropic SDK streams `BetaRawMessageStreamEvent` events.
3. **Retry**: If a transient error occurs, `withRetry()` applies exponential back-off.
4. **Token tracking**: `currentLimits()` accumulates usage from streamed delta events.
5. **Analytics**: Request start/end events are logged to the [Analytics Service](../entities/analytics-service.md).

### Phase 3: Tool Execution

When the model returns `tool_use` blocks, the tool execution pipeline runs:

1. **Partition**: `partitionToolCalls()` (in `services/tools/toolOrchestration.ts`) splits tool calls into concurrency-safe batches (run in parallel, up to `CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY` concurrent = default 10) and non-concurrency-safe batches (run serially).

2. **Per-tool execution** (`services/tools/toolExecution.ts`):
   - Pre-tool hooks fire (`executePreToolHooks`)
   - Permission check (`checkRuleBasedPermissions`)
   - Tool `call()` function executes (filesystem, bash, MCP tool call, etc.)
   - Post-tool hooks fire (`executePostToolHooks`) — can modify tool output
   - Analytics event logged: tool name, duration, file extension, MCP server type

3. **MCP tool routing**: Tools from [MCP Service](../entities/mcp-service.md) are dispatched to the connected MCP client via the MCP SDK. Connection failures surface as tool errors.

4. **Context modifier**: Some tools return a `contextModifier` that updates `ToolUseContext` (e.g., adding new files to the context, updating agent state). Modifiers from concurrent batches are queued and applied after the batch completes.

### Phase 4: Response Streaming

The model's text content and tool results are rendered back to the user via the Ink terminal UI. The query loop yields `StreamEvent` objects that are consumed by React components for display.

### Phase 5: Post-Turn

After each turn:
- `sessionMemoryUpdate()` (if enabled) runs a background forked agent to update the session memory markdown file
- Analytics events for token usage, tool counts, and session state are flushed from the [Analytics Service](../entities/analytics-service.md)'s queue

## Key Interfaces

**API Service entry point:**
```typescript
async function* query(
  messages: Message[],
  tools: Tools,
  options: QueryOptions,
  canUseTool: CanUseToolFn,
): AsyncGenerator<StreamEvent>
```

**Tool orchestration entry point:**
```typescript
async function* runTools(
  toolUseMessages: ToolUseBlock[],
  assistantMessages: AssistantMessage[],
  canUseTool: CanUseToolFn,
  toolUseContext: ToolUseContext,
): AsyncGenerator<MessageUpdate>
```

**Compact check:**
```typescript
async function autoCompactIfNeeded(
  messages: Message[],
  toolUseContext: ToolUseContext,
  cacheSafeParams: CacheSafeParams,
  querySource?: QuerySource,
  tracking?: AutoCompactTrackingState,
): Promise<{ wasCompacted: boolean; compactionResult?: CompactionResult }>
```

**Analytics (fire-and-forget):**
```typescript
function logEvent(eventName: string, metadata: LogEventMetadata): void
```

## See Also

- [API Service](../entities/api-service.md) — Phase 2 model call
- [MCP Service](../entities/mcp-service.md) — Phase 3 external tool dispatch
- [Analytics Service](../entities/analytics-service.md) — threads through all phases
- [Compact Service](../entities/compact-service.md) — Phase 1 context management
- [OAuth Service](../entities/oauth-service.md) — Phase 0 authentication
- [Context Window Management](../concepts/context-window-management.md) — Phase 1 threshold logic
- [Async Event Queue](../concepts/async-event-queue.md) — analytics buffering across all phases
