# Execution Flow

## Overview
Execution Flow describes the end-to-end path a user prompt takes from CLI input through to a final assistant response. Understanding this flow is essential for debugging, extending, and reasoning about Claude Code's behavior, since every feature -- permissions, tools, streaming, compaction -- is wired into specific stages of this pipeline.

## Mechanism

### 1. CLI Entrypoint (`main.tsx`)
The process begins in `main.tsx`, which runs startup side-effects before any heavy imports:
- `profileCheckpoint('main_tsx_entry')` marks the entry for profiling.
- `startMdmRawRead()` fires MDM subprocess reads in parallel with module loading.
- `startKeychainPrefetch()` fires macOS keychain reads for OAuth and API keys.

After imports complete, Commander parses CLI flags (`--permission-mode`, `--model`, `--resume`, etc.), performs authentication, loads settings/managed config, initializes analytics (GrowthBook), and calls `launchRepl()` to hand off to the interactive loop.

### 2. REPL Setup and Session Initialization
The REPL initializes:
- A session ID and working directory (`setCwd`).
- Tool registration via `getTools()`.
- Permission context via `initializeToolPermissionContext()`.
- MCP server connections (`getMcpToolsCommandsAndResources`).
- The `AppState` store that tracks mutable session state.

### 3. `processUserInput`
When the user types a prompt, it enters `processUserInput()` (from `utils/processUserInput/processUserInput.ts`). This function:
- Detects slash commands (e.g., `/help`, `/compact`) and dispatches them.
- Creates a `UserMessage` with the prompt content.
- Resolves attachments (images, files, memory).
- Pushes the user message onto the message array.

### 4. System Prompt Assembly
Before querying the API, the system prompt is assembled via `fetchSystemPromptParts()`:
- A default system prompt describing Claude Code's capabilities and constraints.
- User context (working directory, git branch, OS, available tools).
- System context (environment variables, project config).
- Optional custom/append system prompts from SDK callers.
- Memory mechanics prompt if auto-memory is enabled.

These are concatenated with `asSystemPrompt([ ... ])`.

### 5. `query()` Call
The core loop lives in `query()` (from `query.ts`). It is an `AsyncGenerator` that yields `StreamEvent | RequestStartEvent | Message | TombstoneMessage | ToolUseSummaryMessage` values and returns a `Terminal` when the conversation turn is complete.

Inside `query()`, a `queryLoop()` runs:
1. **Pre-processing**: applies tool result budgets, snip compaction, microcompact, and context collapse to keep the conversation within token limits.
2. **API call**: sends the system prompt, user context, system context, and messages to the Anthropic API via streaming.
3. **Streaming response**: yields `StreamEvent` objects as tokens arrive. The caller (REPL UI or SDK) consumes these to render incremental output.

### 6. Tool Dispatch
When the assistant's response contains `tool_use` blocks:
- `runTools()` (from `services/tools/toolOrchestration.ts`) executes tool calls, potentially in parallel via `StreamingToolExecutor`.
- Each tool call is gated by the [Permission Model](./permission-model.md) through `canUseTool`.
- Tool results are injected as `UserMessage` entries with `tool_result` content blocks.

### 7. Result Injection and Loop-Until-Done
After tools execute:
- Tool results and attachment messages (memory, skill discoveries) are appended to the message array.
- The loop checks stop conditions: `stop_reason === 'end_turn'`, max turns reached, token budget exhausted, or stop hooks firing.
- If the assistant issued tool calls, the loop continues back to step 5 with the expanded message history.
- If the assistant produced a final text response with no tool calls, the loop terminates.

### 8. `QueryEngine` (SDK/Headless Path)
For non-interactive use, `QueryEngine` wraps this lifecycle in a class:
- `submitMessage(prompt)` creates the user message, assembles the system prompt, calls `processUserInput`, then delegates to `query()`.
- It tracks cumulative usage, permission denials, and file state across turns.
- Each `submitMessage` yields `SDKMessage` events to the caller.

## Involved Entities
- [Tool System](../entities/tool-system.md) -- tool registration, dispatch, and result handling
- [Permission System](../entities/permission-system.md) -- gates every tool call
- [Query Engine](../entities/query-engine.md) -- owns the query lifecycle for SDK callers
- [Message System](./message-types-and-streaming.md) -- message types flowing through the pipeline

## Source Evidence
- `src/main.tsx` -- CLI entrypoint, startup side-effects (lines 1-200), Commander setup, `launchRepl()` call
- `src/QueryEngine.ts` -- `QueryEngine` class with `submitMessage()` (line 209+), system prompt assembly (lines 284-325), `processUserInput` integration (line 335+)
- `src/query.ts` -- `query()` generator (line 219), `queryLoop()` (line 241), mutable loop state (line 204), streaming + tool dispatch loop (line 307+)
- `src/utils/processUserInput/processUserInput.ts` -- slash command detection, user message creation
- `src/utils/queryContext.ts` -- `fetchSystemPromptParts()` for system prompt assembly
- `src/services/tools/toolOrchestration.ts` -- `runTools()` for parallel tool execution

## See Also
- [Permission Model](./permission-model.md)
- [Tool Permission Gating](./tool-permission-gating.md)
- [Message Types and Streaming](./message-types-and-streaming.md)
