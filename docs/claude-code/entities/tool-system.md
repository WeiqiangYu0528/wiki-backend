# Tool System

## Overview

The tool system is the pluggable framework powering all Claude Code actions. It provides approximately 40+ built-in tools, each implementing a standard `Tool` interface with input validation, permission checking, execution, progress streaming, and UI rendering. Tools are the primary mechanism through which the AI agent interacts with the user's environment -- reading files, running shell commands, searching code, spawning subagents, and more.

All tools are defined under `tools/` and registered centrally in `tools.ts`. The system supports runtime tool pool assembly, MCP tool wrapping, deferred loading via ToolSearch, deny-rule filtering, and feature-flag-gated conditional inclusion. Tools are assembled into an immutable `Tools` array (aliased as `readonly Tool[]`) and threaded through the query engine into every API turn.

## Key Types

### Tool Interface

The `Tool<Input, Output, Progress>` interface (defined in `Tool.ts`) is generic over three type parameters:

- **Input** -- a Zod object schema (`z.ZodType<{ [key: string]: unknown }>`) that defines and validates the tool's parameters.
- **Output** -- the return type of `call()`.
- **Progress** -- a discriminated union of progress events the tool can emit mid-execution.

Core members of the interface:

```typescript
type Tool<Input, Output, P> = {
  name: string
  aliases?: string[]            // Backwards-compat names after renames
  searchHint?: string           // 3-10 word phrase for ToolSearch keyword matching
  inputSchema: Input            // Zod schema; validated before call()
  maxResultSizeChars: number    // Threshold for persisting large results to disk

  // Lifecycle
  call(args, context, canUseTool, parentMessage, onProgress?): Promise<ToolResult<Output>>
  validateInput?(input, context): Promise<ValidationResult>
  checkPermissions(input, context): Promise<PermissionResult>
  description(input, options): Promise<string>
  prompt(options): Promise<string>

  // Metadata flags
  isConcurrencySafe(input): boolean   // Default: false (assume not safe)
  isReadOnly(input): boolean          // Default: false (assume writes)
  isEnabled(): boolean                // Default: true
  isDestructive?(input): boolean      // Default: false

  // UI rendering
  renderToolUseMessage(input, options): React.ReactNode
  renderToolResultMessage?(content, progress, options): React.ReactNode
  renderToolUseProgressMessage?(progress, options): React.ReactNode
  renderToolUseRejectedMessage?(input, options): React.ReactNode
  renderToolUseErrorMessage?(result, options): React.ReactNode
  renderGroupedToolUse?(toolUses, options): React.ReactNode | null

  // Behavioral
  interruptBehavior?(): 'cancel' | 'block'
  isSearchOrReadCommand?(input): { isSearch: boolean; isRead: boolean; isList?: boolean }
  shouldDefer?: boolean         // Requires ToolSearch round-trip before use
  alwaysLoad?: boolean          // Never deferred, even if ToolSearch is active
  isMcp?: boolean               // True for MCP-proxied tools
  backfillObservableInput?(input): void
  preparePermissionMatcher?(input): Promise<(pattern: string) => boolean>
}
```

### ToolResult

Every `call()` returns a `ToolResult<T>`:

```typescript
type ToolResult<T> = {
  data: T
  newMessages?: (UserMessage | AssistantMessage | AttachmentMessage | SystemMessage)[]
  contextModifier?: (context: ToolUseContext) => ToolUseContext
  mcpMeta?: { _meta?: Record<string, unknown>; structuredContent?: Record<string, unknown> }
}
```

The `contextModifier` field allows a tool to alter the `ToolUseContext` for subsequent tool calls in the same turn. This is only honored for tools that are **not** concurrency-safe (since concurrent tools cannot safely mutate shared context).

### buildTool() Helper

All tool exports go through `buildTool(def)`, which fills in fail-closed defaults for commonly-stubbed methods so callers never need null checks:

| Default | Value |
|---------|-------|
| `isEnabled` | `() => true` |
| `isConcurrencySafe` | `() => false` |
| `isReadOnly` | `() => false` |
| `isDestructive` | `() => false` |
| `checkPermissions` | `() => { behavior: 'allow', updatedInput }` (defer to general permission system) |
| `toAutoClassifierInput` | `() => ''` (skip security classifier) |
| `userFacingName` | `() => name` |

A typical tool definition looks like:

```typescript
export const FileReadTool = buildTool({
  name: 'Read',
  searchHint: 'read files, images, PDFs, notebooks',
  maxResultSizeChars: Infinity,
  strict: true,
  inputSchema: lazySchema(() => z.strictObject({ file_path: z.string(), ... })),
  async description() { return DESCRIPTION },
  async prompt() { ... },
  async call(args, context, canUseTool, parentMessage) { ... },
  checkPermissions(input, context) { ... },
  renderToolUseMessage(input, options) { ... },
  renderToolResultMessage(content, progress, options) { ... },
})
```

### ToolUseContext

`ToolUseContext` is the execution context threaded into every `call()`. It carries:

- **options** -- tools array, model name, MCP clients, thinking config, agent definitions, debug/verbose flags.
- **abortController** -- cooperative cancellation signal.
- **readFileState** -- an LRU file-content cache for dedup.
- **getAppState / setAppState** -- access to the global `AppState` store.
- **messages** -- the current conversation message history.
- **setToolJSX** -- callback to push React nodes into the REPL UI.
- **updateFileHistoryState / updateAttributionState** -- file change tracking for undo/attribution.
- **toolDecisions** -- map of tool-use IDs to accept/reject decisions from hooks.
- **queryTracking** -- chain ID and depth for nested agent queries.
- **requestPrompt** -- factory for interactive prompts (REPL only).
- **contentReplacementState** -- per-thread state for the tool result budget system.

### ToolPermissionContext

Immutable context for permission evaluation:

```typescript
type ToolPermissionContext = DeepImmutable<{
  mode: PermissionMode
  additionalWorkingDirectories: Map<string, AdditionalWorkingDirectory>
  alwaysAllowRules: ToolPermissionRulesBySource
  alwaysDenyRules: ToolPermissionRulesBySource
  alwaysAskRules: ToolPermissionRulesBySource
  isBypassPermissionsModeAvailable: boolean
  shouldAvoidPermissionPrompts?: boolean
  prePlanMode?: PermissionMode
}>
```

## Tool Catalog

### File Operations

| Tool | Name | Description |
|------|------|-------------|
| **FileReadTool** | `Read` | Read files, images, PDFs, Jupyter notebooks. Supports offset/limit for large files. `maxResultSizeChars: Infinity` (never persisted). |
| **FileWriteTool** | `Write` | Write or overwrite file contents. |
| **FileEditTool** | `Edit` | Exact string replacement edits within existing files. |
| **GlobTool** | `Glob` | Fast file pattern matching via glob patterns. |
| **GrepTool** | `Grep` | Content search powered by ripgrep. |
| **NotebookEditTool** | `NotebookEdit` | Edit Jupyter notebook cells (.ipynb). Deferred. |

### Shell

| Tool | Name | Description |
|------|------|-------------|
| **BashTool** | `Bash` | Execute shell commands. Has extensive permission logic (`bashPermissions.ts`), security analysis (`bashSecurity.ts`), command semantics classification, and sed-edit detection. `maxResultSizeChars: 30_000`. |
| **PowerShellTool** | `PowerShell` | Windows shell execution. Conditionally loaded via `isPowerShellToolEnabled()`. |

### AI / Agent

| Tool | Name | Description |
|------|------|-------------|
| **AgentTool** | `Agent` | Spawn isolated subagents with their own conversation context and tool restrictions. |
| **SkillTool** | `Skill` | Invoke registered skills (bundled or user-configured). |
| **SendMessageTool** | `SendMessage` | Send messages to peer agents (UDS inbox). Deferred. |
| **TeamCreateTool** | `TeamCreate` | Create multi-agent swarm teams. Deferred. Feature-gated. |
| **TeamDeleteTool** | `TeamDelete` | Disband a swarm team. Deferred. Feature-gated. |

### Web

| Tool | Name | Description |
|------|------|-------------|
| **WebSearchTool** | `WebSearch` | Search the web for current information. Deferred. |
| **WebFetchTool** | `WebFetch` | Fetch and process web page content. Deferred. |

### Task Management

| Tool | Name | Description |
|------|------|-------------|
| **TaskCreateTool** | `TaskCreate` | Create a background task. Deferred. Feature-gated (`isTodoV2Enabled`). |
| **TaskGetTool** | `TaskGet` | Get task status. Deferred. |
| **TaskListTool** | `TaskList` | List all tasks. Deferred. Read-only, concurrency-safe. |
| **TaskUpdateTool** | `TaskUpdate` | Update task state. Deferred. |
| **TaskStopTool** | `TaskStop` | Stop a running task. Deferred. Concurrency-safe. |
| **TaskOutputTool** | `TaskOutput` | Read output/logs from a background task. Deferred. Aliases: `AgentOutputTool`, `BashOutputTool`. |
| **TodoWriteTool** | `TodoWrite` | Legacy task tracking (when TodoV2 is disabled). Deferred. |

### MCP

| Tool | Name | Description |
|------|------|-------------|
| **MCPTool** | `mcp__<server>__<tool>` | Dynamically created wrappers for tools exposed by MCP servers. Always deferred. Set `isMcp: true`. |
| **ListMcpResourcesTool** | `ListMcpResources` | List resources from connected MCP servers. Deferred. |
| **ReadMcpResourceTool** | `ReadMcpResource` | Read a specific MCP resource by URI. Deferred. Read-only, concurrency-safe. |
| **McpAuthTool** | `McpAuth` | Handle MCP server authentication flows. |

### Planning / Workflow

| Tool | Name | Description |
|------|------|-------------|
| **EnterPlanModeTool** | `EnterPlanMode` | Transition to plan mode (restricts to read-only operations). Deferred. |
| **ExitPlanModeV2Tool** | `ExitPlanMode` | Exit plan mode and resume normal execution. Deferred. |
| **EnterWorktreeTool** | `EnterWorktree` | Create a git worktree for isolated work. Deferred. Feature-gated. |
| **ExitWorktreeTool** | `ExitWorktree` | Exit and optionally remove a worktree. Deferred. |

### Scheduling

| Tool | Name | Description |
|------|------|-------------|
| **CronCreateTool** | `CronCreate` | Schedule a recurring or one-shot prompt. Deferred. Feature-gated (`AGENT_TRIGGERS`). |
| **CronDeleteTool** | `CronDelete` | Cancel a scheduled cron job. Deferred. |
| **CronListTool** | `CronList` | List active cron jobs. Deferred. |
| **RemoteTriggerTool** | `RemoteTrigger` | Manage scheduled remote agent triggers. Deferred. Feature-gated (`AGENT_TRIGGERS_REMOTE`). |

### Utility

| Tool | Name | Description |
|------|------|-------------|
| **ToolSearchTool** | `ToolSearch` | Keyword search to discover and load deferred tools. |
| **ConfigTool** | `Config` | Read/write configuration. Deferred. Ant-only. |
| **BriefTool** | `Brief` | Toggle brief response mode. Read-only, concurrency-safe. |
| **AskUserQuestionTool** | `AskUserQuestion` | Prompt the user with a multiple-choice question. Deferred. |
| **LSPTool** | `LSP` | Language Server Protocol operations. Deferred. Concurrency-safe, read-only. |
| **SleepTool** | `Sleep` | Pause execution. Feature-gated (`PROACTIVE` or `KAIROS`). |

## Tool Lifecycle

A tool invocation proceeds through five stages:

### 1. Input Validation

The tool's `inputSchema` (a Zod schema) is parsed against the model's output. If parsing fails, an error is returned to the model. If the tool defines `validateInput()`, additional semantic checks run (e.g., BashTool validates that `cd` targets are within allowed directories; FileReadTool blocks device paths like `/dev/random`).

### 2. Permission Check

Two layers of permission checking occur:

1. **General permission system** (`permissions.ts`) -- evaluates deny rules, allow rules, and the current `PermissionMode`. Blanket deny rules filter tools out of the pool entirely before the model sees them (`filterToolsByDenyRules`).
2. **Tool-specific `checkPermissions()`** -- each tool can implement custom permission logic. BashTool, for instance, has extensive command-level permission matching in `bashPermissions.ts` with wildcard pattern support via `preparePermissionMatcher()`.

If permission is denied, the tool result is an error message explaining why, and the model can try an alternative approach.

### 3. Execution

`call()` runs the tool's core logic. During execution:

- **Progress streaming** -- tools can emit progress events via the `onProgress` callback. These are typed per-tool (e.g., `BashProgress` includes stdout/stderr chunks; `AgentToolProgress` includes subagent message counts).
- **Abort handling** -- the `abortController` on `ToolUseContext` enables cooperative cancellation. Long-running tools (Bash, Agent) check the signal periodically.
- **Concurrency** -- tools declaring `isConcurrencySafe(input) === true` can run in parallel with other concurrent-safe tools. Non-concurrent-safe tools run sequentially.

### 4. Result Persistence

If the tool result exceeds `maxResultSizeChars`, the full output is persisted to a file on disk, and the model receives a truncated preview with the file path. This prevents context window bloat from large outputs (e.g., verbose shell command output). Tools like FileReadTool set `maxResultSizeChars: Infinity` to opt out of persistence (since persisting a file read result that the model would then re-read creates a circular loop).

### 5. UI Rendering

Tools provide multiple rendering hooks for the terminal UI:

- `renderToolUseMessage()` -- rendered immediately when the tool call is streamed, before execution begins. Input may be partial (still streaming).
- `renderToolUseProgressMessage()` -- updated during execution as progress events arrive.
- `renderToolResultMessage()` -- rendered after completion with the full output.
- `renderToolUseRejectedMessage()` -- shown when the user denies permission.
- `renderToolUseErrorMessage()` -- shown on errors.
- `renderGroupedToolUse()` -- optional batch rendering when multiple instances of the same tool run in parallel (non-verbose mode only).

## Advanced Features

### Deferred Loading (ToolSearch)

When the tool pool is large (especially with many MCP tools), sending full schemas for all tools in every API request wastes context tokens. The ToolSearch system addresses this:

1. Tools with `shouldDefer: true` (or all MCP tools unless they set `alwaysLoad: true`) are sent to the API with `defer_loading: true` -- the model sees only the tool name and `searchHint`, not the full input schema.
2. When the model needs a deferred tool, it calls `ToolSearchTool` with a keyword query or `select:<tool_name>` syntax.
3. ToolSearch returns the full schema definitions for matched tools, making them callable on subsequent turns.
4. The `isDeferredTool()` function in `tools/ToolSearchTool/prompt.ts` controls deferral logic.

ToolSearch availability is gated by `isToolSearchEnabledOptimistic()`, which checks whether the tool count exceeds a threshold.

### Progress Streaming

Each tool category has its own typed progress events:

- `BashProgress` -- stdout/stderr chunks, exit code updates.
- `AgentToolProgress` -- subagent message counts, model info.
- `MCPProgress` -- MCP protocol-level events.
- `WebSearchProgress` -- search result streaming.
- `SkillToolProgress` -- skill execution status.
- `TaskOutputProgress` -- background task log updates.

Progress events are dispatched via `ToolCallProgress<P>` callbacks and rendered through `renderToolUseProgressMessage()`.

### Context Modifiers

A tool's `ToolResult` can include a `contextModifier` function that transforms the `ToolUseContext` for subsequent tool calls in the same turn. This is used by tools like EnterPlanMode and EnterWorktree that need to change the execution environment mid-conversation. Context modifiers are only honored for non-concurrency-safe tools.

### Concurrency Safety

The `isConcurrencySafe(input)` flag controls whether a tool can execute in parallel with other tools in the same model turn. Safe tools (like FileRead, Grep, Glob, TaskList, LSP) run concurrently for better throughput. Unsafe tools (the default) run sequentially to prevent race conditions. The `StreamingToolExecutor` and tool orchestration layer in `services/tools/` enforce this.

### Tool Pool Assembly

The tool pool is assembled through several layers in `tools.ts`:

1. **`getAllBaseTools()`** -- exhaustive list of all tools, gated by feature flags and environment variables.
2. **`getTools(permissionContext)`** -- filters by deny rules and `isEnabled()` checks. In `CLAUDE_CODE_SIMPLE` mode, returns only Bash/Read/Edit.
3. **`assembleToolPool(permissionContext, mcpTools)`** -- merges built-in tools with MCP tools, deduplicates by name (built-in wins), and sorts for prompt-cache stability.

Built-in tools are sorted as a contiguous prefix to preserve API-level cache keys -- interleaving MCP tools would invalidate downstream cache entries.

### MCP Tool Wrapping

MCP servers expose tools via the Model Context Protocol. These are wrapped as `MCPTool` instances with `isMcp: true` and `mcpInfo: { serverName, toolName }`. Their `inputJSONSchema` comes directly from the MCP server (bypassing Zod), and they are always deferred unless they set `_meta['anthropic/alwaysLoad']`. The `filterToolsByDenyRules` function supports MCP server-prefix deny rules (e.g., `mcp__server`) to strip all tools from a server.

## Source Files

| File | Description |
|------|-------------|
| `Tool.ts` | Core `Tool` interface, `ToolUseContext`, `ToolResult`, `buildTool()` helper, `ToolPermissionContext`, progress types |
| `tools.ts` | Tool registration, `getAllBaseTools()`, `getTools()`, `assembleToolPool()`, feature-flag gating, deny-rule filtering |
| `tools/BashTool/BashTool.tsx` | Shell execution tool with command semantics, progress streaming, image output handling |
| `tools/BashTool/bashPermissions.ts` | Extensive command-level permission matching with wildcard patterns |
| `tools/FileReadTool/FileReadTool.ts` | File/image/PDF/notebook reading with token limits and caching |
| `tools/FileEditTool/FileEditTool.ts` | Exact string replacement editing |
| `tools/AgentTool/AgentTool.ts` | Subagent spawning and management |
| `tools/SkillTool/SkillTool.ts` | Skill invocation dispatch |
| `tools/MCPTool/MCPTool.ts` | MCP tool wrapper |
| `tools/ToolSearchTool/ToolSearchTool.ts` | Deferred tool discovery and loading |
| `tools/ToolSearchTool/prompt.ts` | `isDeferredTool()` logic, deferral rules |
| `services/tools/toolExecution.ts` | Tool call execution, result persistence, context modifier application |
| `services/tools/toolOrchestration.ts` | Sequential/parallel tool orchestration |
| `services/tools/StreamingToolExecutor.ts` | Streaming execution with concurrent tool support |
| `utils/permissions/permissions.ts` | General permission system, `getDenyRuleForTool()` |
| `utils/toolResultStorage.ts` | Large result persistence to disk |

## See Also

- [Permission System](permission-system.md) -- layered permission gating that governs tool execution
- [Agent System](agent-system.md) -- subagent spawning powered by AgentTool
- [Query Engine](query-engine.md) -- the conversation loop that dispatches tool calls
- [Tool Permission Gating](../concepts/tool-permission-gating.md) -- cross-cutting concept for how tools are allowed/denied
