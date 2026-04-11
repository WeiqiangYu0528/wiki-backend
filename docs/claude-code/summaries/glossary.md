# Glossary

Alphabetical definitions of domain-specific terms used throughout Claude Code.

---

## A

### AgentDefinition
Union type encompassing all agent variants: `BuiltInAgentDefinition`, `CustomAgentDefinition`, and `PluginAgentDefinition`. Each variant shares `BaseAgentDefinition` fields (`agentType`, `whenToUse`, `tools`, `model`, `permissionMode`, etc.) and adds a source-specific `getSystemPrompt` method. Defined in `src/tools/AgentTool/loadAgentsDir.ts`. See [Agent System](../entities/agent-system.md).

### AgentDefinitionsResult
Container returned by `getAgentDefinitionsWithOverrides()`. Holds `activeAgents` (deduplicated by priority: built-in < plugin < user < project < flag < policy) and `allAgents` (the full unfiltered list), plus optional `failedFiles` and `allowedAgentTypes`. See [Agent System](../entities/agent-system.md).

### AgentId
Branded string type (`src/types/ids.ts`) that uniquely identifies a subagent within a session. Assigned when the Agent tool spawns a child and threaded through `ToolUseContext.agentId` so hooks and telemetry can distinguish subagent calls from the main thread. See [Agent System](../entities/agent-system.md).

### AppState
Central immutable state tree for the entire application, defined in `src/state/AppStateStore.ts`. Wraps settings, permission context, MCP connections, tasks, plugins, file history, attribution, todos, speculation, and UI state in a `DeepImmutable<>` wrapper. Mutated only via `setAppState(prev => next)`. See [State Management](../entities/state-management.md).

### AppStateStore
A `Store<AppState>` instance that provides reactive `get`/`set`/`subscribe` semantics for `AppState`. See [State Management](../entities/state-management.md).

### AttachmentMessage
A message subtype that carries file content or CLAUDE.md injections attached to the conversation context. Created by `createAttachmentMessage()` and typically appended alongside user messages. See [Message Pipeline](../entities/message-pipeline.md).

## B

### BaseAgentDefinition
Shared field set for all agent types. Includes `agentType`, `whenToUse`, `tools`, `disallowedTools`, `skills`, `mcpServers`, `hooks`, `color`, `model`, `effort`, `permissionMode`, `maxTurns`, `memory`, `isolation`, `background`, and `initialPrompt`. Extended by `BuiltInAgentDefinition`, `CustomAgentDefinition`, and `PluginAgentDefinition`. See [Agent System](../entities/agent-system.md).

### BundledSkillDefinition
Type for skills compiled into the CLI binary (`src/skills/bundledSkills.ts`). Fields include `name`, `description`, `context` (`'inline'` or `'fork'`), optional `allowedTools`, `model`, `hooks`, `agent`, and `files` (reference files extracted to disk on first use). The `getPromptForCommand` callback produces the prompt content blocks. See [Skill System](../entities/skill-system.md).

### BuiltInAgentDefinition
Agent variant with `source: 'built-in'` and `baseDir: 'built-in'`. Has a `getSystemPrompt(params)` method that receives `toolUseContext` for dynamic prompt generation. Examples include the general-purpose agent, explore agent, and plan agent. See [Agent System](../entities/agent-system.md).

## C

### CLAUDE.md
Project-level configuration files that inject instructions into the system prompt. Loaded from a hierarchy of locations (user home, project root, subdirectories) and merged via the `@include` directive. Supports nested memory attachments and is deduped per session via `loadedNestedMemoryPaths`. See [Configuration](../concepts/configuration.md).

### Compaction
The process of summarizing conversation history when it grows too long for the context window. Managed via `CompactProgressEvent` which emits `hooks_start`, `compact_start`, and `compact_end` events. Pre-compact and post-compact hooks run around the summarization step. See [Context Management](../concepts/context-management.md).

### ContentReplacementState
Per-conversation-thread state for the tool result budget system (`src/utils/toolResultStorage.ts`). Tracks which tool results have been persisted to disk and replaced with previews. Main thread provisions once; subagents clone or reconstruct from sidechain records. See [Context Management](../concepts/context-management.md).

### CustomAgentDefinition
Agent variant for user-defined agents from markdown files or JSON in settings. Has `source: SettingSource` (userSettings, projectSettings, policySettings, etc.) and a `getSystemPrompt()` closure that captures the parsed prompt content. Parsed by `parseAgentFromMarkdown()` or `parseAgentFromJson()`. See [Agent System](../entities/agent-system.md).

## D

### DenialTrackingState
Tracks consecutive permission denials in classifier modes (auto, headless). When the denial count exceeds a threshold, the system falls back to interactive prompting. Stored in both `AppState.denialTracking` and `ToolUseContext.localDenialTracking` (the latter for async subagents whose `setAppState` is a no-op). See [Permission System](../entities/permission-system.md).

## F

### FileStateCache
LRU cache class (`src/utils/fileStateCache.ts`) that stores file content keyed by path, bounded by both entry count and total byte size. Used as `ToolUseContext.readFileState` to avoid redundant disk reads within a query turn. Supports `clone()` and `merge()` for subagent forking. See [Tool Execution](../entities/tool-execution.md).

## I

### @include
Directive used inside CLAUDE.md files to inline content from other files or globs. Processed during the CLAUDE.md loading phase to build a composite set of instructions for the system prompt. See [Configuration](../concepts/configuration.md).

## L

### LocalAgentTask
A task type (`type: 'local_agent'`) representing a subagent running as a background process on the local machine. Its state type is `LocalAgentTaskState`. Task IDs are prefixed with `'a'`. See [Task System](../entities/task-system.md).

## M

### MCPServerConnection
Discriminated union of MCP server states: `ConnectedMCPServer`, `FailedMCPServer`, `NeedsAuthMCPServer`, `PendingMCPServer`, and `DisabledMCPServer`. Each variant carries `name`, `type`, and `config: ScopedMcpServerConfig`. Connected servers additionally hold the `Client` instance and `capabilities`. Defined in `src/services/mcp/types.ts`. See [MCP Integration](../entities/mcp-integration.md).

### MCPTool
A `Tool` instance created from an MCP server's advertised tool. Identified by `isMcp: true` and `mcpInfo: { serverName, toolName }`. May use `shouldDefer` for lazy loading via ToolSearch, or `alwaysLoad` to bypass deferral. Input schema is supplied as raw JSON Schema via `inputJSONSchema`. See [MCP Integration](../entities/mcp-integration.md).

### Message
Top-level union type for all conversation messages. Includes `UserMessage`, `AssistantMessage`, `SystemMessage`, `AttachmentMessage`, `ProgressMessage`, `TombstoneMessage`, `ToolUseSummaryMessage`, and `SystemCompactBoundaryMessage`. Carried in `ToolUseContext.messages` and the REPL message list. See [Message Pipeline](../entities/message-pipeline.md).

## P

### PermissionBehavior
Literal union `'allow' | 'deny' | 'ask'` representing the three possible permission verdicts applied to a tool use request. See [Permission System](../entities/permission-system.md).

### PermissionDecisionReason
Discriminated union explaining why a permission decision was made. Variants include `rule` (matched a permission rule), `mode` (determined by permission mode), `hook` (decided by a hook), `classifier` (decided by the auto-mode classifier), `sandboxOverride`, `asyncAgent`, `workingDir`, `safetyCheck`, and `other`. See [Permission System](../entities/permission-system.md).

### PermissionMode
Union type `'acceptEdits' | 'bypassPermissions' | 'default' | 'dontAsk' | 'plan' | 'auto' | 'bubble'`. Controls how tool permission checks behave session-wide. `'default'` prompts for dangerous operations; `'bypassPermissions'` auto-allows everything; `'plan'` restricts to read-only; `'auto'` uses a classifier to decide. Defined in `src/types/permissions.ts`. See [Permission System](../entities/permission-system.md).

### PermissionResult
The return type of `Tool.checkPermissions()`. A union of `PermissionAllowDecision`, `PermissionAskDecision`, `PermissionDenyDecision`, and a `passthrough` variant that defers to the general permission system. Each variant may carry `updatedInput`, `suggestions` for rule changes, and `pendingClassifierCheck` for async classifier evaluation. See [Permission System](../entities/permission-system.md).

### PermissionRule
A single permission rule combining `source: PermissionRuleSource`, `ruleBehavior: PermissionBehavior`, and `ruleValue: PermissionRuleValue` (which specifies `toolName` and optional `ruleContent` pattern like `"git *"`). See [Permission System](../entities/permission-system.md).

### PluginAgentDefinition
Agent variant with `source: 'plugin'` and an additional `plugin` field identifying the providing plugin. Has a `getSystemPrompt()` closure like `CustomAgentDefinition`. Loaded by `loadPluginAgents()`. See [Agent System](../entities/agent-system.md).

### ProgressMessage
A message subtype that carries real-time progress data (`ToolProgressData`) during tool execution. Subtypes include `BashProgress`, `AgentToolProgress`, `MCPProgress`, `SkillToolProgress`, `WebSearchProgress`, and `REPLToolProgress`. See [Message Pipeline](../entities/message-pipeline.md).

## R

### RemoteAgentTask
A task type (`type: 'remote_agent'`) representing an agent running in a remote Claude Code Runtime (CCR) environment. Its state type is `RemoteAgentTaskState`. Task IDs are prefixed with `'r'`. See [Task System](../entities/task-system.md).

### runAgent
Core function in `src/tools/AgentTool/runAgent.ts` that executes a subagent. Sets up a `ToolUseContext` fork via `createSubagentContext`, resolves the agent model, registers hooks, connects agent-specific MCP servers, calls `query()` in a loop, and records the sidechain transcript. Returns the assistant's final output. See [Agent System](../entities/agent-system.md).

## S

### Settings Hierarchy
The layered configuration system where settings are merged in priority order: CLI args > local settings > project settings (`.claude/settings.json`) > user settings (`~/.claude/settings.json`) > policy/managed settings > flag settings. Each layer can define permission rules, MCP servers, agent definitions, and hooks. See [Configuration](../concepts/configuration.md).

### Sidechain
A transcript recording of a subagent's conversation, written to session storage by `recordSidechainTranscript()`. Enables post-hoc inspection of agent behavior and is used to reconstruct `ContentReplacementState` when resuming background agents. See [Agent System](../entities/agent-system.md).

### SkillDefinition
See `BundledSkillDefinition`. Skills are slash-command-like prompt injections that can run in two execution contexts: `'inline'` (executed within the current conversation turn) or `'fork'` (spawned as a subagent with its own context). Skills may specify `allowedTools`, a dedicated `model`, and `hooks`. See [Skill System](../entities/skill-system.md).

### Speculation
A performance optimization where Claude Code speculatively executes the next likely tool calls while the model is still generating. Managed via `SpeculationState` in `AppState`, which tracks active speculations, their written paths (overlay), completion boundaries, and pipelining state. See [Speculation](../concepts/speculation.md).

## T

### Task
Interface in `src/Task.ts` representing a background operation. Has `name`, `type: TaskType`, and a `kill(taskId, setAppState)` method. Concrete task types include local shell, local agent, remote agent, in-process teammate, local workflow, monitor MCP, and dream. See [Task System](../entities/task-system.md).

### TaskState
Discriminated union of all concrete task state types: `LocalShellTaskState`, `LocalAgentTaskState`, `RemoteAgentTaskState`, `InProcessTeammateTaskState`, `LocalWorkflowTaskState`, `MonitorMcpTaskState`, and `DreamTaskState`. Stored in `AppState.tasks` keyed by task ID. See [Task System](../entities/task-system.md).

### TaskStatus
Literal union `'pending' | 'running' | 'completed' | 'failed' | 'killed'` representing the lifecycle of a background task. Terminal states (`completed`, `failed`, `killed`) are checked by `isTerminalTaskStatus()`. See [Task System](../entities/task-system.md).

### TaskType
Literal union `'local_bash' | 'local_agent' | 'remote_agent' | 'in_process_teammate' | 'local_workflow' | 'monitor_mcp' | 'dream'` identifying the kind of background task. Each type has a single-character ID prefix (e.g., `'b'` for bash, `'a'` for agent). See [Task System](../entities/task-system.md).

### Tool
The primary tool interface (`src/Tool.ts`), generic over `<Input, Output, Progress>`. Defines the full lifecycle: `inputSchema`, `call()`, `description()`, `checkPermissions()`, `validateInput()`, rendering methods (`renderToolUseMessage`, `renderToolResultMessage`, etc.), and metadata like `isConcurrencySafe`, `isReadOnly`, `isDestructive`, `shouldDefer`, and `maxResultSizeChars`. Built via `buildTool()` which fills safe defaults. See [Tool Execution](../entities/tool-execution.md).

### ToolPermissionContext
Immutable context object threaded through permission checks. Contains the current `PermissionMode`, `additionalWorkingDirectories`, and three rule maps: `alwaysAllowRules`, `alwaysDenyRules`, and `alwaysAskRules` (each typed as `ToolPermissionRulesBySource`). See [Permission System](../entities/permission-system.md).

### ToolPermissionRulesBySource
Record type `{ [T in PermissionRuleSource]?: string[] }` mapping each rule source (userSettings, projectSettings, localSettings, etc.) to an array of pattern strings. Used for the allow, deny, and ask rule sets within `ToolPermissionContext`. See [Permission System](../entities/permission-system.md).

### ToolResult
Generic return type from `Tool.call()`. Contains `data: T` (the tool's output), optional `newMessages` to inject into the conversation, an optional `contextModifier` callback (honored only for non-concurrency-safe tools), and optional `mcpMeta` for MCP protocol passthrough. See [Tool Execution](../entities/tool-execution.md).

### ToolUseContext
Large context object passed to every tool invocation (`src/Tool.ts`). Provides access to `options` (model, tools, MCP clients, agent definitions), `abortController`, `readFileState` (FileStateCache), `getAppState`/`setAppState`, the current `messages` array, permission-related callbacks, file history, attribution tracking, and numerous optional hooks for UI, notifications, and telemetry. See [Tool Execution](../entities/tool-execution.md).

### Tools
Readonly array alias `readonly Tool[]` used throughout the codebase to pass tool collections. Defined in `src/Tool.ts` as a semantic type to make tool-set assembly and filtering easier to track. See [Tool Execution](../entities/tool-execution.md).

## W

### Worktree
Git worktree isolation mode for agents. When an agent definition sets `isolation: 'worktree'`, it runs in a separate git worktree so its file edits do not affect the main working tree. Managed by `EnterWorktree`/`ExitWorktree` tools. See [Agent System](../entities/agent-system.md).
