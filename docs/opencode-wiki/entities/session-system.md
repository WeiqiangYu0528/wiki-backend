# Session System

## Overview

The session system is the heart of OpenCode's agent runtime. Every conversation between the user and the AI, every tool invocation result, and every compaction event is anchored to a `Session.Info` record persisted in the SQLite database. Sessions form a tree: top-level sessions are created by the user; child sessions are spawned by the agent to handle subproblems. Sessions carry optional workspace linkage for cloud sync, snapshot-based revert pointers, and a share URL when published.

The Session namespace lives in `src/session/index.ts` and is consumed by virtually every other subsystem — the TUI, the HTTP server, the agent runner, compaction, and the prompt builder all read from or write to session state.

## Key Types

### Session.Info

The primary Zod schema and TypeScript type describing a session record. All fields map to columns in `SessionTable` (the Drizzle schema in `session.sql.ts`).

```typescript
Session.Info = z.object({
  id:          SessionID,             // ULID-based opaque ID
  slug:        z.string(),            // URL-friendly human-readable identifier
  projectID:   ProjectID,             // owning project (maps to working directory)
  workspaceID: WorkspaceID.optional(), // cloud workspace (optional)
  directory:   z.string(),            // absolute path of the project root at creation time
  parentID:    SessionID.optional(),  // set when this is a child/forked session
  title:       z.string(),            // human-readable title; defaults to a timestamp string
  version:     z.string(),            // schema version for forward-compat
  time: {
    created:    number,               // Unix ms timestamp of row creation
    updated:    number,               // Unix ms timestamp of last mutation
    compacting: number | undefined,   // non-null while compaction is in progress
    archived:   number | undefined,   // set when the session is archived
  },
  summary: {                          // optional — populated after session ends
    additions: number,
    deletions: number,
    files:     number,
    diffs:     Snapshot.FileDiff[] | undefined,
  } | undefined,
  share: {
    url: string,                      // public share URL if published
  } | undefined,
  revert: {
    messageID: MessageID,             // message the session can be reverted to
    partID:    PartID | undefined,
    snapshot:  string | undefined,    // filesystem snapshot key
    diff:      string | undefined,    // patch diff for display
  } | undefined,
  permission: Permission.Ruleset | undefined, // override permission rules for this session
})
```

The schema is exported with `.meta({ ref: "Session" })` so it appears in the generated JSON schema catalog used by the API layer.

### Session.GlobalInfo

An extended view that attaches the owning project summary to the session. Used by the server API and TUI session list.

```typescript
Session.GlobalInfo = Session.Info.extend({
  project: {
    id:       ProjectID,
    name:     string | undefined,
    worktree: string,   // absolute path to the git worktree
  } | null,
})
```

### Session.ProjectInfo

Lightweight project summary embedded in `GlobalInfo`.

```typescript
Session.ProjectInfo = z.object({
  id:       ProjectID,
  name:     z.string().optional(),
  worktree: z.string(),
})
```

### DB row mapping (SessionTable)

The Drizzle table schema maps `Session.Info` fields to snake_case columns. Key non-obvious mappings:

| Info field | DB column |
|------------|-----------|
| `projectID` | `project_id` |
| `workspaceID` | `workspace_id` (nullable) |
| `parentID` | `parent_id` (nullable) |
| `time.created` | `time_created` |
| `time.updated` | `time_updated` |
| `time.compacting` | `time_compacting` (nullable) |
| `time.archived` | `time_archived` (nullable) |
| `summary.additions` | `summary_additions` (nullable) |
| `summary.deletions` | `summary_deletions` (nullable) |
| `summary.files` | `summary_files` (nullable) |
| `summary.diffs` | `summary_diffs` (nullable JSON) |
| `share?.url` | `share_url` (nullable) |
| `revert` | `revert` (nullable JSON) |
| `permission` | `permission` (nullable JSON) |

The `Session.fromRow(row)` and `Session.toRow(info)` functions perform the two-way conversion. `fromRow` also reconstructs the optional `summary` object — it is only set if at least one of the three stats columns is non-null.

### Default title constants

```typescript
const parentTitlePrefix = "New session - "
const childTitlePrefix  = "Child session - "
```

`createDefaultTitle(isChild = false)` concatenates the appropriate prefix with `new Date().toISOString()`, producing titles such as `"New session - 2025-03-15T10:23:41.000Z"`.

`Session.isDefaultTitle(title)` tests the title against the regex:

```
^(New session - |Child session - )\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$
```

The TUI uses this to determine whether to show a "rename session" prompt.

### MessageV2 error types (from `message-v2.ts`)

The session message layer defines named typed errors for all failure modes during a prompt turn:

| Error name | Description |
|------------|-------------|
| `MessageOutputLengthError` | Model output exceeded configured token limit |
| `MessageAbortedError` | User or signal cancelled the in-flight request; carries `message: string` |
| `StructuredOutputError` | Structured output mode validation failed; carries `message` and `retries` count |
| `ProviderAuthError` | Authentication failed for the selected provider; carries `providerID` and `message` |
| `APIError` | HTTP-level error from the provider; carries `statusCode`, `isRetryable`, `responseHeaders`, `responseBody`, and `metadata` |
| `ContextOverflowError` | Prompt exceeded the model's context window; carries `message` and optional `responseBody` |

### SessionPrompt.Interface (from `prompt.ts`)

`SessionPrompt.Service` is an Effect Service that exposes:

```typescript
interface Interface {
  assertNotBusy(sessionID: SessionID): Effect<void, Session.BusyError>
  cancel(sessionID: SessionID): Effect<void>
  prompt(input: PromptInput): Effect<MessageV2.WithParts>
  loop(input: LoopInput): Effect<MessageV2.WithParts>
  shell(input: ShellInput): Effect<MessageV2.WithParts>
  command(input: CommandInput): Effect<MessageV2.WithParts>
  resolvePromptParts(template: string): Effect<PromptInput["parts"]>
}
```

The `prompt` method is the main execution path for user-facing turns. `loop` is used for structured output mode. `shell` handles direct shell command injection. `command` handles slash-command dispatch.

## Architecture

```
src/session/
  index.ts          <-- Session.Info type, DB serialization, CRUD, bus events
  message-v2.ts     <-- MessageV2 namespace: typed errors, part/message schemas
  prompt.ts         <-- SessionPrompt.Service: prompt execution entry point
  system.ts         <-- SystemPrompt builder
  compaction.ts     <-- SessionCompaction: summarize + truncate message history
  summary.ts        <-- SessionSummary: diff stats aggregation
  revert.ts         <-- SessionRevert: snapshot-based undo
  instruction.ts    <-- Instruction.Service: dynamic system prompt fragments
  llm.ts            <-- LLM: raw AI SDK call wrapper
  processor.ts      <-- SessionProcessor: streaming response handler
  status.ts         <-- SessionStatus: busy/idle state machine
  todo.ts           <-- Todo.Service: session-scoped todo list
  session.sql.ts    <-- Drizzle table definitions (SessionTable, MessageTable, PartTable)
  schema.ts         <-- SessionID, MessageID, PartID branded ID types
  prompt/
    plan.txt        <-- Plan mode prompt fragment
    build-switch.txt
    max-steps.txt
```

`Session` (index.ts) is a pure data module — it reads and writes rows but has no Effect Service of its own. The stateful, process-scoped logic lives in `SessionPrompt.Service` and `SessionStatus`. This separation keeps the persistence layer testable in isolation.

The session system depends on `Provider` (to resolve the model for a turn), `ToolRegistry` (to fetch the active tool list), and `Permission` (to gate destructive tool calls). It does not own any of those systems; it calls into them during `SessionPrompt.prompt()`.

## Runtime Behavior

### Session creation

1. A caller (CLI, TUI, HTTP server) calls `Session.create({ projectID, directory, title?, parentID? })`.
2. A ULID is generated for `id`; `Slug.generate()` produces the human-readable `slug`.
3. If no title is supplied, `createDefaultTitle(isChild)` produces `"New session - <ISO>"` for top-level sessions or `"Child session - <ISO>"` for child sessions.
4. `time.created` and `time.updated` are both set to `Date.now()`.
5. The row is inserted into `SessionTable`.
6. A `session.created` sync event is published on the bus so subscribers (TUI list, cloud sync) receive the update.

### Fork naming

`getForkedTitle(title)` appends `" (fork #1)"` to the title on first fork and increments on subsequent forks. This is used when a session is branched from a revert point.

### Prompt execution via SessionPrompt

When the user submits a prompt (from TUI, CLI `run`, or HTTP API):

1. `SessionPrompt.assertNotBusy(sessionID)` is called. If another prompt is already running, `Session.BusyError` is thrown immediately.
2. The `SystemPrompt` builder assembles the system prompt from: project-level config markdown, agent profile, active `Instruction.Service` fragments, and variant-specific text files (`plan.txt`, `build-switch.txt`, `max-steps.txt`).
3. `ToolRegistry.tools(model, agent?)` is called to obtain the filtered list of tools appropriate for the current model and agent context.
4. The full message history (from `MessageTable` + `PartTable`) is loaded and optionally compacted via `SessionCompaction`.
5. The AI SDK call is made via `LLM`, wrapping the provider's `languageModel` or `responses` API.
6. Streaming parts are processed by `SessionProcessor` which writes `PartTable` rows incrementally, publishes bus events for each chunk, and handles tool call dispatch.
7. After all tool calls complete and the model finishes, the final `MessageV2.WithParts` is returned and `time.updated` is bumped on the session row.

### Compaction tracking

When context-window compaction begins, `time.compacting` is set to the current timestamp. The field remains non-null for the duration of the summarization operation. UI clients observe this field to display a "compacting…" indicator. On completion (success or failure), the field is cleared by a row update with `time_compacting: null`.

### Revert

A session's `revert` field stores the `messageID` (and optional `partID`) of the message the user can roll back to. `SessionRevert` reads the `snapshot` key, restores the filesystem state from the stored snapshot, then truncates `MessageTable` and `PartTable` to remove all rows after that point.

### Bus events emitted by session operations

| Event type | Payload | When emitted |
|------------|---------|--------------|
| `session.created` | `{ sessionID, info }` | After row insert |
| `session.updated` | `{ sessionID, info }` | After any `Session.update()` call |
| `session.deleted` | `{ sessionID }` | After row deletion |
| `session.title` | `{ sessionID, title }` | When the agent auto-updates the title |

All events use `aggregate: "sessionID"` for ordered delivery to subscribers (TUI session list, cloud sync layer).

## Source Files

| File | Key exports / functions |
|------|------------------------|
| `src/session/index.ts` | `Session.Info` (Zod schema + type), `Session.GlobalInfo`, `Session.ProjectInfo`, `Session.fromRow()`, `Session.toRow()`, `Session.isDefaultTitle()`, `Session.Event.*`, `createDefaultTitle()`, `getForkedTitle()` |
| `src/session/message-v2.ts` | `MessageV2` namespace, typed error constructors (`OutputLengthError`, `AbortedError`, `StructuredOutputError`, `AuthError`, `APIError`, `ContextOverflowError`), `OutputFormatText`, `OutputFormatJsonSchema` |
| `src/session/prompt.ts` | `SessionPrompt.Service`, `SessionPrompt.Interface`, `PromptInput`, `LoopInput`, `ShellInput`, `CommandInput`, prompt variant text imports |
| `src/session/compaction.ts` | `SessionCompaction` — summarizes old messages and replaces them with a compact summary |
| `src/session/system.ts` | `SystemPrompt` — assembles the system prompt from config, instructions, and agent profile |
| `src/session/instruction.ts` | `Instruction.Service` — manages per-session dynamic system prompt fragments |
| `src/session/revert.ts` | `SessionRevert` — snapshot-based message history rollback |
| `src/session/status.ts` | `SessionStatus` — idle/busy state machine |
| `src/session/todo.ts` | `Todo.Service` — session-scoped todo items consumed by `TodoWriteTool` |
| `src/session/llm.ts` | `LLM` — raw AI SDK call wrapper with retry and streaming |
| `src/session/processor.ts` | `SessionProcessor` — streaming response handler, writes `PartTable` rows |
| `src/session/session.sql.ts` | `SessionTable`, `MessageTable`, `PartTable` Drizzle table definitions |
| `src/session/schema.ts` | `SessionID`, `MessageID`, `PartID` branded ID types |
| `src/session/prompt/plan.txt` | Plan mode system prompt fragment |
| `src/session/prompt/build-switch.txt` | Build/switch mode prompt fragment |
| `src/session/prompt/max-steps.txt` | Max-steps limit prompt fragment |

## See Also

- [Tool System](tool-system.md)
- [Provider System](provider-system.md)
- [CLI Runtime](cli-runtime.md)
- [Context Compaction and Session Recovery](../syntheses/context-compaction-and-session-recovery.md)
- [Tool and Agent Composition](../concepts/tool-and-agent-composition.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Request to Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
