# Agent System

## Overview

The agent subsystem enables Claude Code to spawn isolated sub-agents for complex tasks. Each agent runs as an independent conversation with its own tool set, permission mode, MCP servers, system prompt, and optional worktree isolation. Agents are defined via markdown frontmatter (custom agents), code (built-in agents), or plugins, and are loaded from `~/.claude/agents/`, project-local `.claude/agents/`, policy settings, or bundled source.

The core tool name is `Agent` (legacy wire name `Task`). When invoked, the parent model specifies a `prompt`, a `subagent_type` (selecting which agent definition to use), and optional overrides for model, isolation, and background execution. The agent subsystem resolves the definition, assembles a filtered tool pool, constructs an isolated context, and runs an async generator loop that calls `query()` until the agent completes or hits its turn limit.

## Key Types

### BaseAgentDefinition

All agent definitions share this base shape, defined in `loadAgentsDir.ts`:

| Field | Type | Description |
|---|---|---|
| `agentType` | `string` | Unique identifier used as `subagent_type` |
| `whenToUse` | `string` | Natural language description shown to the parent model |
| `tools` | `string[]?` | Allowlist of tool names (`['*']` = all tools) |
| `disallowedTools` | `string[]?` | Denylist of tool names (applied after allowlist) |
| `skills` | `string[]?` | Skill names to preload via frontmatter |
| `mcpServers` | `AgentMcpServerSpec[]?` | Agent-specific MCP servers (reference by name or inline definition) |
| `hooks` | `HooksSettings?` | Session-scoped hooks registered when the agent starts |
| `permissionMode` | `PermissionMode?` | Override parent's permission mode |
| `model` | `string?` | Model override (`'inherit'` = use parent's model) |
| `effort` | `EffortValue?` | Effort level override |
| `maxTurns` | `number?` | Maximum agentic turns before forced stop |
| `memory` | `AgentMemoryScope?` | Persistent memory scope: `'user'`, `'project'`, or `'local'` |
| `isolation` | `'worktree' \| 'remote'?` | Git worktree isolation or remote execution |
| `background` | `boolean?` | Always run as background task |
| `initialPrompt` | `string?` | Prepended to the first user turn |
| `omitClaudeMd` | `boolean?` | Strip CLAUDE.md from agent's user context (saves tokens for read-only agents) |
| `color` | `AgentColorName?` | Terminal color for the agent's output |
| `requiredMcpServers` | `string[]?` | MCP server name patterns that must be configured for agent availability |

### BuiltInAgentDefinition

Extends `BaseAgentDefinition` with `source: 'built-in'` and a dynamic `getSystemPrompt(params)` callback that receives `toolUseContext`. Built-in agents are registered in code and always available (unless disabled via env var).

### CustomAgentDefinition

Extends `BaseAgentDefinition` with `source: SettingSource` (one of `'userSettings'`, `'projectSettings'`, `'policySettings'`, `'flagSettings'`). The system prompt is loaded from the markdown body and accessed via `getSystemPrompt()`. When `memory` is enabled, the memory prompt is appended dynamically.

### PluginAgentDefinition

Extends `BaseAgentDefinition` with `source: 'plugin'` and a `plugin: string` field identifying the providing plugin. Loaded via `loadPluginAgents()`.

### AgentDefinitionsResult

```typescript
type AgentDefinitionsResult = {
  activeAgents: AgentDefinition[]   // Deduplicated by agentType (later sources override earlier)
  allAgents: AgentDefinition[]      // All loaded agents including overridden duplicates
  failedFiles?: Array<{ path: string; error: string }>
  allowedAgentTypes?: string[]
}
```

The priority order for deduplication is: built-in < plugin < userSettings < projectSettings < flagSettings < policySettings.

## Built-in Agents

Built-in agents are registered in `builtInAgents.ts` via `getBuiltInAgents()`. The set varies based on feature flags, environment, and entrypoint.

| Agent | Type | Model | Description |
|---|---|---|---|
| **General Purpose** | `general-purpose` | default subagent model | Wildcard tool access (`['*']`). For researching complex questions, searching code, and executing multi-step tasks. |
| **Explore** | `Explore` | `haiku` (external), `inherit` (internal) | Read-only codebase exploration specialist. Fast file search, regex grep, file reading. Disallows Agent, Edit, Write, NotebookEdit, ExitPlanMode. Omits CLAUDE.md and gitStatus from context to save tokens. |
| **Plan** | `Plan` | `inherit` | Software architect for designing implementation plans. Read-only. Same disallowed tools as Explore. Omits CLAUDE.md. |
| **Claude Code Guide** | `claude-code-guide` | -- | Helps users understand and use Claude Code, Agent SDK, and Claude API. Only included for non-SDK entrypoints. |
| **Statusline Setup** | `statusline-setup` | -- | Creates or updates the statusLine command in user settings by converting shell PS1 configuration. |
| **Verification** | `verification` | -- | Verification specialist that tries to break implementations rather than confirm they work. Feature-gated behind `VERIFICATION_AGENT` and `tengu_hive_evidence`. Cannot modify project files. |
| **Fork** | `fork` (synthetic) | `inherit` | Not registered in builtInAgents. Used when `subagent_type` is omitted and the fork subagent experiment is active. Inherits parent's exact tool pool and system prompt for prompt cache hits. Permission mode: `bubble`. |

Additionally, when `CLAUDE_CODE_COORDINATOR_MODE` is enabled, `getCoordinatorAgents()` replaces the standard set with coordinator-specific worker agents.

The env var `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS` disables all built-in agents in non-interactive (SDK) mode.

## Agent Lifecycle

### 1. Definition Loading

`getAgentDefinitionsWithOverrides(cwd)` (memoized) loads agents from three sources:

- **Built-in**: `getBuiltInAgents()` returns code-defined agents
- **Custom**: `loadMarkdownFilesForSubdir('agents', cwd)` loads markdown files from `~/.claude/agents/` (user), `.claude/agents/` (project), and policy/flag settings. Each file is parsed via `parseAgentFromMarkdown()` which extracts frontmatter fields (`name`, `description`, `tools`, `model`, `effort`, `permissionMode`, `maxTurns`, `mcpServers`, `hooks`, `skills`, `memory`, `isolation`, `background`, `initialPrompt`, `color`) and uses the markdown body as the system prompt.
- **Plugin**: `loadPluginAgents()` loads agents provided by plugins (memoized)

In `CLAUDE_CODE_SIMPLE` mode, only built-in agents are returned.

### 2. Tool Resolution

`resolveAgentTools()` in `agentToolUtils.ts` filters the parent's assembled tool pool:

- If `tools` contains `'*'`, all tools are available (minus universal denylist)
- Otherwise, only explicitly listed tools are included
- `disallowedTools` are removed after allowlist filtering
- `ALL_AGENT_DISALLOWED_TOOLS` are always removed (e.g., tools that should never be available to subagents)
- Async agents have additional restrictions via `ASYNC_AGENT_ALLOWED_TOOLS`
- Custom (non-built-in) agents have extra restrictions via `CUSTOM_AGENT_DISALLOWED_TOOLS`

### 3. MCP Server Setup

`initializeAgentMcpServers()` in `runAgent.ts` processes agent-specific MCP servers:

- **Reference by name** (string): Looks up existing MCP config via `getMcpConfigByName()` and connects using the shared memoized `connectToServer()`. These shared clients are NOT cleaned up when the agent finishes.
- **Inline definition** (`{ [name]: McpServerConfig }`): Creates a new, agent-scoped connection. These newly created clients ARE cleaned up on agent completion.
- When `strictPluginOnlyCustomization` locks MCP to plugin-only, frontmatter MCP servers are skipped for user-controlled agents but allowed for admin-trusted sources (plugin, built-in, policySettings).
- Agent MCP tools are merged with resolved agent tools via `uniqBy()` deduplication.

### 4. Context Creation

`createSubagentContext()` from `utils/forkedAgent.ts` builds the isolated `ToolUseContext`:

- **Sync agents**: Share `setAppState` and `abortController` with the parent
- **Async agents**: Get a new unlinked `AbortController` and isolated state
- Both share `setResponseLength` for response metrics
- The file state cache is either cloned from the parent (fork path) or freshly created with `READ_FILE_STATE_CACHE_SIZE`
- User context may have CLAUDE.md stripped (`omitClaudeMd`) and system context may have `gitStatus` stripped (for Explore/Plan agents)
- Permission mode is overridden if the agent defines one, unless the parent is in `bypassPermissions`, `acceptEdits`, or `auto` mode
- Effort level is overridden if defined on the agent

### 5. Hook Registration

`registerFrontmatterHooks()` registers session-scoped hooks from the agent's frontmatter:

- Hooks are scoped to the agent's lifecycle via `agentId`
- `Stop` hooks are converted to `SubagentStop` (since subagents trigger SubagentStop, not Stop)
- Hooks are blocked for user-controlled agents when `strictPluginOnlyCustomization` locks hooks to plugin-only
- `SubagentStart` hooks are executed and their `additionalContexts` are injected as attachment messages

### 6. Skills Preloading

If the agent defines `skills: [...]`, each skill is resolved (with fallback to plugin-namespaced and suffix matching), loaded concurrently, and injected as user messages into the initial message list.

### 7. Execution

`runAgent()` is an async generator that:

1. Writes initial transcript and agent metadata to session storage (fire-and-forget)
2. Iterates over `query()` messages in a `for await` loop
3. Forwards `stream_event` message_start events to the parent's API metrics
4. Records each `AssistantMessage`, `UserMessage`, `ProgressMessage`, or `SystemCompactBoundaryMessage` to the sidechain transcript via `recordSidechainTranscript()`
5. Yields recordable messages back to the caller (`AgentTool.tsx`)
6. Stops when `query()` exhausts, `maxTurns` is reached (via `max_turns_reached` attachment), or the abort controller fires

### 8. Cleanup

The `finally` block in `runAgent()` performs comprehensive cleanup:

- `mcpCleanup()`: Shuts down agent-specific (inline) MCP servers
- `clearSessionHooks()`: Removes hooks registered for this agent
- `cleanupAgentTracking()`: Releases prompt cache tracking state
- `readFileState.clear()`: Releases cloned file state cache memory
- `initialMessages.length = 0`: Releases cloned fork context messages
- `unregisterPerfettoAgent()`: Releases perfetto trace registry entry
- `clearAgentTranscriptSubdir()`: Releases transcript subdir mapping
- Removes agent's todos entry from `AppState.todos`
- `killShellTasksForAgent()`: Kills background bash tasks spawned by the agent
- `killMonitorMcpTasksForAgent()`: Kills monitor MCP tasks (feature-gated)

## Isolation Model

### File State Cache Cloning

Each agent gets its own file state cache. Fork agents clone the parent's cache; regular agents start fresh. The cache is explicitly cleared in the cleanup phase to prevent memory leaks.

### Per-Agent Working Directories

Agents can run in a different working directory via the `cwd` parameter on the Agent tool input. This overrides all filesystem and shell operations within the agent.

### Worktree-Based Isolation

When `isolation: 'worktree'` is set (via frontmatter or tool input), `createAgentWorktree()` creates a temporary git worktree so the agent works on an isolated copy of the repository. Changes in the worktree do not affect the main working tree. The worktree is cleaned up via `removeAgentWorktree()` after the agent completes.

### Unlinked AbortControllers

Async agents receive a new `AbortController` independent of the parent's. This means canceling the parent does not automatically cancel running async agents -- they must be explicitly killed via `killAsyncAgent()`.

### Agent-Specific MCP Servers

Inline MCP server definitions create connections scoped to the agent's lifetime. Referenced (by-name) servers share the parent's connection and are not affected by agent cleanup.

## Memory and Skills

### Agent Memory

Agents can have persistent memory scoped to one of three levels:

| Scope | Directory | Description |
|---|---|---|
| `user` | `~/.claude/agent-memory/<agentType>/` | Per-user, shared across all projects |
| `project` | `<cwd>/.claude/agent-memory/<agentType>/` | Per-project, checked into VCS |
| `local` | `<cwd>/.claude/agent-memory-local/<agentType>/` | Per-project, not checked into VCS |

When memory is enabled, the agent's system prompt is dynamically appended with `loadAgentMemoryPrompt()`, and Write/Edit/Read tools are automatically injected into the tool set (if not already present) so the agent can read and write memory files.

Memory snapshots (`AGENT_MEMORY_SNAPSHOT` feature) allow project-level snapshots to bootstrap a user's local memory on first use, with update prompts when newer snapshots become available.

### Skills Preloading

Skills specified in agent frontmatter (`skills: [skill1, skill2]`) are resolved at agent startup using multiple strategies:
1. Exact match via `hasCommand()`
2. Fully-qualified with the agent's plugin prefix
3. Suffix match on `:skillName` for plugin-namespaced skills

Loaded skill content is injected as user messages with metadata for UI display.

## Agent Resumption

`resumeAgent.ts` supports resuming background agents from their persisted sidechain transcript. It reads the agent's metadata (including `agentType` and optional `worktreePath`), reconstructs the message history, resolves the agent definition, and re-enters the `runAgent()` loop with the restored context.

## Source Files

| File | Description |
|---|---|
| `tools/AgentTool/AgentTool.tsx` | Main tool definition: input schema, `call()` entry point, permission checks, UI rendering, background/worktree/multi-agent orchestration |
| `tools/AgentTool/runAgent.ts` | Core `runAgent()` async generator: context setup, MCP init, query loop, transcript recording, cleanup |
| `tools/AgentTool/loadAgentsDir.ts` | Type definitions, markdown/JSON parsing, agent definition loading and caching |
| `tools/AgentTool/builtInAgents.ts` | `getBuiltInAgents()` registry with feature-flag gating |
| `tools/AgentTool/agentToolUtils.ts` | `resolveAgentTools()`, tool filtering, YOLO classification, progress tracking |
| `tools/AgentTool/agentMemory.ts` | `AgentMemoryScope` type, memory directory resolution, `loadAgentMemoryPrompt()` |
| `tools/AgentTool/agentMemorySnapshot.ts` | Memory snapshot checking and initialization |
| `tools/AgentTool/agentColorManager.ts` | Per-agent terminal color assignment |
| `tools/AgentTool/agentDisplay.ts` | Agent display formatting |
| `tools/AgentTool/constants.ts` | `AGENT_TOOL_NAME`, `LEGACY_AGENT_TOOL_NAME`, `ONE_SHOT_BUILTIN_AGENT_TYPES` |
| `tools/AgentTool/forkSubagent.ts` | Fork subagent experiment: `isForkSubagentEnabled()`, `FORK_AGENT` definition, context message building |
| `tools/AgentTool/prompt.ts` | Agent tool prompt/description generation, agent list formatting |
| `tools/AgentTool/resumeAgent.ts` | `resumeAgentBackground()` for resuming agents from sidechain transcripts |
| `tools/AgentTool/UI.tsx` | React UI components for agent tool use rendering |
| `tools/AgentTool/built-in/exploreAgent.ts` | Explore agent definition and system prompt |
| `tools/AgentTool/built-in/planAgent.ts` | Plan agent definition and system prompt |
| `tools/AgentTool/built-in/generalPurposeAgent.ts` | General-purpose agent definition |
| `tools/AgentTool/built-in/verificationAgent.ts` | Verification agent definition |
| `tools/AgentTool/built-in/claudeCodeGuideAgent.ts` | Claude Code Guide agent definition |
| `tools/AgentTool/built-in/statuslineSetup.ts` | Statusline setup agent definition |

## See Also

- [Tool System](tool-system.md)
- [Skill System](skill-system.md)
- [Task System](task-system.md)
- [Agent Isolation](../concepts/agent-isolation.md)
- [Agent-Tool-Skill Triad](../syntheses/agent-tool-skill-triad.md)
