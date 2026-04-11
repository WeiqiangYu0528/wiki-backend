# Overview — Claude Code Tools System

**Type:** Summary
**Source:** `/Users/weiqiangyu/Downloads/wiki/docs/claude_code/src/tools`

---

## What This Is

The `tools/` directory is the action layer of Claude Code. It contains approximately 40 TypeScript modules — one per tool — that Claude can invoke during a conversation. Each tool has a well-defined input schema, output schema, permission model, and UI rendering logic. Together they form the executable surface through which Claude interacts with the operating system, the file system, the network, external APIs, and other agents.

---

## Tool Inventory

The full set of tools covers these functional categories:

| Category | Tools |
|----------|-------|
| Shell execution | BashTool, PowerShellTool |
| File system | FileReadTool, FileWriteTool, FileEditTool, GlobTool, GrepTool, LSPTool |
| Agent orchestration | AgentTool, SendMessageTool, RemoteTriggerTool |
| Task/todo management | TaskCreateTool, TaskGetTool, TaskListTool, TaskOutputTool, TaskStopTool, TaskUpdateTool, TodoWriteTool |
| MCP integration | MCPTool, McpAuthTool, ListMcpResourcesTool, ReadMcpResourceTool |
| Web/network | WebFetchTool, WebSearchTool |
| Notebook editing | NotebookEditTool |
| User interaction | AskUserQuestionTool, BriefTool, SyntheticOutputTool |
| Planning / mode control | EnterPlanModeTool, ExitPlanModeTool, EnterWorktreeTool, ExitWorktreeTool |
| Skills and config | SkillTool, ConfigTool, ToolSearchTool |
| Scheduling | ScheduleCronTool, SleepTool |
| REPL | REPLTool |
| Teams | TeamCreateTool, TeamDeleteTool |

---

## Shared Architecture: `buildTool()`

Every tool is constructed by calling `buildTool(def: ToolDef)` from `../../Tool.ts`. This factory enforces a standard interface contract:

```ts
interface ToolDef<InputSchema, Output> {
  name: string
  description(): Promise<string>
  prompt(): Promise<string>
  inputSchema: InputSchema          // Zod schema
  outputSchema: OutputSchema        // Zod schema
  call(input, context): Promise<{data: Output}>
  checkPermissions(input, context): Promise<PermissionResult>
  renderToolUseMessage(...)
  renderToolResultMessage(...)
  userFacingName(): string
  // ...optional lifecycle hooks
}
```

This uniformity enables Claude Code to dynamically assemble a tool pool (`assembleToolPool()`), pass it to the model, and route tool-use blocks back to the right handler at runtime.

---

## Key Subsystems

### 1. BashTool (Shell Execution)

The largest single tool subsystem with 18 source files. It implements shell command execution with:
- A layered security model blocking dangerous shell patterns
- Wildcard-based permission rules
- Sandbox isolation support
- Background task handling
- Output truncation and image detection

See [entity_bashtool.md](entity_bashtool.md) for details.

### 2. AgentTool (Sub-agent Orchestration)

The most architecturally significant tool with 14+ files. It enables Claude to spawn sub-agents that:
- Run locally in-process or remotely in cloud environments
- Operate in the background with progress tracking
- Work in isolated git worktrees
- Communicate via SendMessage

See [entity_agenttool.md](entity_agenttool.md) for details.

### 3. Permission System

A cross-cutting concern implemented in `utils/permissions/` and referenced by every tool. It decides whether an action is auto-allowed, requires user confirmation, or is blocked outright.

See [concept_permissions.md](concept_permissions.md) for details.

---

## Data Flow

```
User message
    └─> Claude model
           └─> tool_use block (tool name + input JSON)
                  └─> Tool.call(input, context)
                         ├─> checkPermissions()  ──> block / ask / allow
                         ├─> execute action
                         └─> tool_result ──> back to model
```

The model may chain many tool calls before producing a final assistant response. AgentTool invocations create new independent chains running concurrently.

---

## Cross-References

- [index.md](index.md) — full navigation
- [entity_bashtool.md](entity_bashtool.md) — shell execution detail
- [entity_agenttool.md](entity_agenttool.md) — sub-agent orchestration detail
- [concept_permissions.md](concept_permissions.md) — permission model
- [synthesis_composition.md](synthesis_composition.md) — how tools compose
- [schema.md](schema.md) — wiki conventions
- [log.md](log.md) — analysis decisions
