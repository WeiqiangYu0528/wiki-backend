# Tool System

## Overview

The tool system defines OpenCode's complete actionable surface: bash execution, file reading/writing/editing, pattern search (glob, grep), web fetch and search, code search, LSP diagnostics, patch application, task spawning, todo tracking, skill invocation, question prompting, and experimental batch/plan tooling. It is also where plugin-defined custom tools are merged into the built-in catalog.

Every capability the agent can exercise at runtime — every side-effecting action — flows through this layer. The tool layer is what turns a language model invocation into a coding agent.

## Key Types

### Tool.Def

The core definition type that every tool must satisfy.

```typescript
interface Tool.Def<Parameters extends z.ZodType, M extends Metadata> {
  description: string
  parameters: Parameters                    // Zod schema for the tool's input
  execute(
    args: z.infer<Parameters>,
    ctx: Tool.Context,
  ): Promise<{
    title:       string                     // short display label for the TUI
    metadata:    M                          // tool-specific output metadata
    output:      string                     // text result returned to the model
    attachments?: Omit<MessageV2.FilePart, "id" | "sessionID" | "messageID">[]
  }>
  formatValidationError?(error: z.ZodError): string  // optional custom error message
}
```

### Tool.Info

The registerable wrapper around a `Tool.Def`. The `init` function is called once per tool during registry construction, with an optional `agent` context.

```typescript
interface Tool.Info<Parameters, M> {
  id:   string
  init: (ctx?: Tool.InitContext) => Promise<Tool.Def<Parameters, M>>
}
```

`Tool.define(id, init)` is the factory function used by every built-in tool. It wraps `init` with:
- Zod argument validation (throws with a structured message if args are invalid)
- Automatic output truncation via `Truncate.output()` — long outputs are written to a temp file and a pointer is returned in `metadata.outputPath`

### Tool.Context

Runtime context passed to every tool's `execute` function.

```typescript
type Tool.Context = {
  sessionID:  SessionID
  messageID:  MessageID
  agent:      string
  abort:      AbortSignal              // fired when user cancels the turn
  callID?:    string
  extra?:     Record<string, any>
  messages:   MessageV2.WithParts[]   // full message history for context-aware tools
  metadata(input: { title?: string; metadata?: M }): void  // push UI updates mid-execution
  ask(input: Omit<Permission.Request, "id" | "sessionID" | "tool">): Promise<void>  // request permission
}
```

The `ask()` callback is how tools integrate with the permission system. When a destructive operation is about to occur (writing a file, executing a shell command that touches the filesystem), the tool calls `ctx.ask(...)`, which suspends execution until the user approves or denies the request.

### ToolRegistry.Interface

The Effect Service interface exposed by the registry.

```typescript
interface ToolRegistry.Interface {
  ids(): Effect<string[]>
  named: {
    task: Tool.Info
    read: Tool.Info
  }
  tools(
    model: { providerID: ProviderID; modelID: ModelID },
    agent?: Agent.Info,
  ): Effect<(Tool.Def & { id: string })[]>
}
```

The `tools()` method is the primary access point. It returns the filtered, initialized list of tools for the given model and agent combination. Tools such as `codesearch` and `websearch` are only included when the provider is `opencode` or `OPENCODE_ENABLE_EXA` is set.

## Architecture

```
src/tool/
  registry.ts       <-- ToolRegistry.Service: builds and filters the full tool list
  tool.ts           <-- Tool.define(), Tool.Def, Tool.Info, Tool.Context types
  bash.ts           <-- BashTool: shell command execution
  read.ts           <-- ReadTool: file content reading
  write.ts          <-- WriteTool: file writing (creates or overwrites)
  edit.ts           <-- EditTool: surgical string replacement in files
  glob.ts           <-- GlobTool: filesystem pattern matching
  grep.ts           <-- GrepTool: ripgrep-based content search
  webfetch.ts       <-- WebFetchTool: HTTP fetch + markdown conversion
  websearch.ts      <-- WebSearchTool: web search (Exa API)
  codesearch.ts     <-- CodeSearchTool: semantic code search (Exa)
  task.ts           <-- TaskTool: spawn a sub-agent task
  todo.ts           <-- TodoWriteTool: update session todo list
  skill.ts          <-- SkillTool: load and execute a named skill
  question.ts       <-- QuestionTool: ask user a clarifying question
  apply_patch.ts    <-- ApplyPatchTool: apply a unified diff patch
  lsp.ts            <-- LspTool: query LSP for diagnostics/completions
  batch.ts          <-- BatchTool: run multiple tools in parallel (experimental)
  plan.ts           <-- PlanExitTool: signal end of planning phase (experimental)
  invalid.ts        <-- InvalidTool: placeholder for unknown tool calls
  truncate.ts       <-- Truncate.output(): shared output-truncation helper
  multiedit.ts      <-- MultiEditTool: apply multiple edits in one call
  ls.ts             <-- LsTool: list directory contents
```

The registry (`registry.ts`) imports all built-in tool constructors, calls `Tool.define()` / `build()` on each, and then assembles the final ordered list in the `all()` function. Plugin-defined tools are appended after all built-ins.

## Runtime Behavior

### Registry initialization

1. `ToolRegistry.layer` is provided via Effect's `Layer.effect`. On first access it resolves `Config.Service` and `Plugin.Service`.
2. `InstanceState.make` creates per-instance state: a `custom: Tool.Info[]` array holding plugin-contributed and file-system-discovered tools.
3. Config directories are scanned for `{tool,tools}/*.{js,ts}` files. Each matching file is dynamically imported; each export is wrapped with `fromPlugin()` and added to `custom`.
4. Loaded plugins (`Plugin.Service.list()`) are iterated; each plugin's `tool` map entries are also wrapped with `fromPlugin()`.
5. All built-in tools are constructed via `build()`, which calls `Tool.define()` if not already done (most tools are eagerly built at module init time).

### Tool filtering by model

The `tools(model, agent?)` Effect applies the following filters before returning the list:

- `codesearch` and `websearch` are only included when `model.providerID === ProviderID.opencode` or `Flag.OPENCODE_ENABLE_EXA` is set.
- The `question` tool (`QuestionTool`) is only included when `Flag.OPENCODE_CLIENT` is `"app"`, `"cli"`, or `"desktop"`, or when `Flag.OPENCODE_ENABLE_QUESTION_TOOL` is set. This prevents non-interactive agents from stalling on user input.
- `LspTool` is only included when `Flag.OPENCODE_EXPERIMENTAL_LSP_TOOL` is set.
- `BatchTool` is only included when `config.experimental?.batch_tool === true`.
- `PlanExitTool` is only included when `Flag.OPENCODE_EXPERIMENTAL_PLAN_MODE` is set and `Flag.OPENCODE_CLIENT === "cli"`.
- Custom plugin tools are always appended after the built-in list.

### Argument validation and truncation

Every tool's `execute` is wrapped by `Tool.define` to run Zod validation before calling the original implementation. If validation fails and the tool defines `formatValidationError`, that formatter is used; otherwise a generic message is thrown.

After execution, `Truncate.output(result.output, {}, agent)` is called. If the output exceeds the per-agent token budget, the content is written to a temp file under `Global.Path.tmp` and the returned `output` is a truncation notice. The `metadata.outputPath` field carries the temp file path so the TUI can offer a "view full output" action.

## Built-in Tool Reference

| Tool ID | Source file | Primary capability |
|---------|-------------|-------------------|
| `bash` | `bash.ts` | Execute shell commands; tracks filesystem side effects for permission gating; supports PowerShell on Windows; default 2-minute timeout |
| `read` | `read.ts` | Read file contents with optional line range |
| `write` | `write.ts` | Create or overwrite a file |
| `edit` | `edit.ts` | Surgical string replacement within a file |
| `multiedit` | `multiedit.ts` | Apply multiple edits to one or more files in a single call |
| `glob` | `glob.ts` | Pattern-based file discovery (`**/*.ts`, etc.) |
| `grep` | `grep.ts` | ripgrep-based content search with regex support |
| `ls` | `ls.ts` | List directory contents |
| `webfetch` | `webfetch.ts` | Fetch a URL and convert HTML to markdown |
| `websearch` | `websearch.ts` | Web search via Exa API (provider-gated) |
| `codesearch` | `codesearch.ts` | Semantic code search via Exa (provider-gated) |
| `apply_patch` | `apply_patch.ts` | Apply a unified diff patch to the working tree |
| `task` | `task.ts` | Spawn a sub-agent with its own session |
| `todo` | `todo.ts` | Write or update the session-scoped todo list |
| `plan` | `plan.ts` | Exit planning phase and begin execution (experimental) |
| `question` | `question.ts` | Ask the user a question and await their reply |
| `skill` | `skill.ts` | Load and execute a named skill from the skill library |
| `lsp` | `lsp.ts` | Query LSP server for diagnostics, completions, hover info (experimental) |
| `batch` | `batch.ts` | Run multiple tool calls in parallel (experimental) |

The `invalid` tool is a sentinel used when the model emits an unrecognized tool name; it returns a descriptive error telling the model to check the available tool list.

### BashTool internals

`bash.ts` uses tree-sitter to parse the command text and extract:
- **Directories touched** (`dirs: Set<string>`) — used to pre-check filesystem permissions
- **Patterns matched** (`patterns: Set<string>`) — used to infer which files may be affected

The sets `CWD`, `FILES`, `FLAGS`, `SWITCHES`, and `PS` classify command tokens. PowerShell (`pwsh`/`powershell`) is detected separately. The default timeout is `Flag.OPENCODE_EXPERIMENTAL_BASH_DEFAULT_TIMEOUT_MS` or 2 minutes. All output is streamed via `ChildProcess` and capped at `MAX_METADATA_LENGTH` (30,000 characters) in the metadata field.

### Plugin tool registration

Plugin tools are integrated via `fromPlugin(id, def)`, which converts the plugin `ToolDefinition` shape into a `Tool.Info`:

```typescript
function fromPlugin(id: string, def: ToolDefinition): Tool.Info {
  return {
    id,
    init: async (initCtx) => ({
      parameters: z.object(def.args),
      description: def.description,
      execute: async (args, toolCtx) => {
        const pluginCtx = { ...toolCtx, directory, worktree } as PluginToolContext
        const result = await def.execute(args, pluginCtx)
        const out = await Truncate.output(result, {}, initCtx?.agent)
        return { title: "", output: out.truncated ? out.content : result, metadata: { ... } }
      },
    }),
  }
}
```

File-system tools discovered in `{tool,tools}/*.{js,ts}` within config directories use the filename as the namespace; exports named `default` use only the namespace, while named exports become `<namespace>_<exportName>`.

## Source Files

| File | Key exports / functions |
|------|------------------------|
| `src/tool/registry.ts` | `ToolRegistry.Service`, `ToolRegistry.Interface`, `ToolRegistry.layer`, `all()`, `tools()`, `ids()`, `fromPlugin()` |
| `src/tool/tool.ts` | `Tool.define()`, `Tool.Def`, `Tool.Info`, `Tool.Context`, `Tool.InitContext`, `Tool.InferParameters`, `Tool.InferMetadata` |
| `src/tool/bash.ts` | `BashTool`, tree-sitter AST scanning, `MAX_METADATA_LENGTH`, `DEFAULT_TIMEOUT`, PowerShell detection |
| `src/tool/read.ts` | `ReadTool` |
| `src/tool/write.ts` | `WriteTool` |
| `src/tool/edit.ts` | `EditTool` |
| `src/tool/multiedit.ts` | `MultiEditTool` |
| `src/tool/glob.ts` | `GlobTool` |
| `src/tool/grep.ts` | `GrepTool` |
| `src/tool/ls.ts` | `LsTool` |
| `src/tool/webfetch.ts` | `WebFetchTool` |
| `src/tool/websearch.ts` | `WebSearchTool` |
| `src/tool/codesearch.ts` | `CodeSearchTool` |
| `src/tool/apply_patch.ts` | `ApplyPatchTool` |
| `src/tool/task.ts` | `TaskTool` |
| `src/tool/todo.ts` | `TodoWriteTool` |
| `src/tool/plan.ts` | `PlanExitTool` |
| `src/tool/question.ts` | `QuestionTool` |
| `src/tool/skill.ts` | `SkillTool` |
| `src/tool/lsp.ts` | `LspTool` |
| `src/tool/batch.ts` | `BatchTool` |
| `src/tool/truncate.ts` | `Truncate.output()` |
| `src/tool/invalid.ts` | `InvalidTool` |

## See Also

- [Provider System](provider-system.md)
- [Session System](session-system.md)
- [Plugin System](plugin-system.md)
- [Tool and Agent Composition](../concepts/tool-and-agent-composition.md)
- [Provider Tool Plugin Interaction Model](../syntheses/provider-tool-plugin-interaction-model.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Request to Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
