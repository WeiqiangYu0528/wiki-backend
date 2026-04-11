# Agent-Tool-Skill Triad

## Overview

This synthesis describes how agents, tools, and skills interact recursively to form the core execution model of Claude Code. An Agent is invoked via `AgentTool` (itself a `Tool`), which spawns a subagent running `query()` with a filtered toolset. Skills are invoked via `SkillTool` (another `Tool`) and can either run inline (injecting prompt content into the current conversation) or fork (spawning a subagent via `runAgent()`). This creates a recursive execution chain: **Agent -> Tool -> Skill -> Agent**.

## Systems Involved

- [Agent System](../entities/agent-system.md) -- agent definitions, lifecycle, and subagent context
- [Tool System](../entities/tool-system.md) -- the `Tool` interface, `buildTool()`, and tool orchestration
- [Skill System](../entities/skill-system.md) -- skill commands, discovery, and execution modes
- [Query Engine](../entities/query-engine.md) -- the `query()` function that drives each agent's main loop

## Interaction Model

### The Recursive Chain

```
User prompt
  |
  v
QueryEngine.submitMessage()
  |
  v
query() loop  <-----------------------------+
  |                                          |
  v                                          |
API call -> assistant response               |
  |                                          |
  +-- tool_use: AgentTool ------------------>|
  |     |                                    |
  |     v                                    |
  |   AgentTool.call()                       |
  |     |                                    |
  |     v                                    |
  |   runAgent()                             |
  |     |-- createSubagentContext()           |
  |     |-- resolveAgentTools() [filtered]   |
  |     |-- initializeAgentMcpServers()      |
  |     +-- query() [recursive entry] -------+
  |                                          |
  +-- tool_use: SkillTool ------------------>|
        |                                    |
        v                                    |
      SkillTool.call()                       |
        |                                    |
        +-- [inline mode]                    |
        |     Returns prompt content;        |
        |     caller injects into messages   |
        |                                    |
        +-- [fork mode]                      |
              executeForkedSkill()            |
                |                            |
                v                            |
              runAgent() ------------------->+
```

### AgentTool: The Agent Spawner

`AgentTool` (`src/tools/AgentTool/AgentTool.tsx`) is a standard `Tool` registered alongside Bash, FileRead, etc. When the model emits a `tool_use` block with `name: "Agent"`, the tool orchestration layer calls `AgentTool.call()`, which:

1. Resolves the `subagent_type` to an `AgentDefinition` (from built-in agents, `.claude/agents/` directory definitions, or the general-purpose default).
2. Calls `resolveAgentTools()` to compute a filtered tool pool -- agents receive a subset of the parent's tools (disallowing `AgentTool` itself for custom agents to cap recursion depth, along with other disallowed tools from `ALL_AGENT_DISALLOWED_TOOLS` and `CUSTOM_AGENT_DISALLOWED_TOOLS`).
3. Calls `runAgent()`, which creates a `ToolUseContext` via `createSubagentContext()`, optionally initializes agent-specific MCP servers via `initializeAgentMcpServers()`, and enters the `query()` loop.
4. Collects streaming messages from the subagent, emitting progress events back to the parent.

Agents can run synchronously (blocking the parent) or asynchronously in the background (`run_in_background: true`), and can be isolated via git worktrees (`isolation: "worktree"`).

### SkillTool: The Skill Executor

`SkillTool` (`src/tools/SkillTool/SkillTool.ts`) resolves skill names to `Command` objects (slash commands). It has two execution modes:

- **Inline mode**: The skill's prompt content is returned directly as the tool result. The model receives the expanded prompt instructions and follows them in the current conversation context. The tool result may include `allowedTools` and `model` overrides from the skill's frontmatter.
- **Fork mode**: The skill calls `executeForkedSkill()`, which prepares a forked command context and calls `runAgent()` with the skill prompt. This spawns a full subagent loop, and the result text is extracted and returned as the tool result.

The fork/inline decision is controlled by the skill's frontmatter (`fork: true`). Forked skills get their own `agentId` and token budget.

### Tool Filtering and Scope Narrowing

Each layer in the recursion narrows the available toolset:

- **Parent agent**: Full tool pool from `assembleToolPool()` + MCP tools
- **Subagent (via AgentTool)**: Filtered by `filterToolsForAgent()`, which removes tools in `ALL_AGENT_DISALLOWED_TOOLS`. Custom agents additionally lose tools in `CUSTOM_AGENT_DISALLOWED_TOOLS`. Agent definitions can specify an explicit `allowed_tools` list.
- **Forked skill (via SkillTool)**: Inherits the parent's tools but runs through `prepareForkedCommandContext()`, which may apply skill-specific tool constraints from frontmatter.

### MCP Server Inheritance

Subagents inherit their parent's MCP clients by default. Agent definitions can additionally declare `mcpServers` in their frontmatter, which `initializeAgentMcpServers()` connects on agent start and cleans up on agent finish. These are additive -- the agent sees parent MCP tools plus its own.

## Key Interfaces

### Tool (from `src/Tool.ts`)

```typescript
type Tool<Input, Output, P> = {
  name: string
  call(args, context: ToolUseContext, canUseTool, parentMessage, onProgress?): Promise<ToolResult<Output>>
  inputSchema: Input
  checkPermissions(input, context): Promise<PermissionResult>
  isConcurrencySafe(input): boolean
  isReadOnly(input): boolean
  // ... rendering, validation, etc.
}
```

### AgentTool Input

```typescript
// Simplified from the actual schema
{
  description: string    // Short task description
  prompt: string         // The task for the agent
  subagent_type?: string // Agent definition to use
  model?: 'sonnet' | 'opus' | 'haiku'
  run_in_background?: boolean
  isolation?: 'worktree' | 'remote'
}
```

### SkillTool Input

```typescript
{
  skill: string   // Skill name (e.g., "commit", "review-pr")
  args?: string   // Optional arguments
}
```

### SkillTool Output (union)

```typescript
// Inline mode
{ success: boolean, commandName: string, allowedTools?: string[], model?: string, status: 'inline' }

// Fork mode
{ success: boolean, commandName: string, status: 'forked', agentId: string, result: string }
```

### runAgent() Entry Point (`src/tools/AgentTool/runAgent.ts`)

```typescript
function runAgent(params: {
  agentDefinition: AgentDefinition
  promptMessages: Message[]
  toolUseContext: ToolUseContext
  canUseTool: CanUseToolFn
  isAsync: boolean
  querySource: QuerySource
  model?: ModelAlias
  availableTools: Tools
  override?: { agentId: AgentId }
}): AsyncGenerator<Message>
```

## See Also

- [Agent System](../entities/agent-system.md) -- agent definitions, built-in agents, agent lifecycle
- [Tool System](../entities/tool-system.md) -- the `Tool` interface and `buildTool()` factory
- [Skill System](../entities/skill-system.md) -- skill commands, frontmatter parsing, discovery
- [Query Engine](../entities/query-engine.md) -- the `query()` loop that agents execute within
- [MCP System](../entities/mcp-system.md) -- agent-specific MCP server initialization
- [Permission System](../entities/permission-system.md) -- `canUseTool` callback threaded through each layer
- [Query Loop Orchestration](./query-loop-orchestration.md) -- how `query()` drives tool execution
- [Permission Enforcement Pipeline](./permission-enforcement-pipeline.md) -- how permissions are checked at each tool call
