# Request to Session Execution Flow

## Overview

This synthesis traces a complete OpenCode request from the moment a user invokes
`opencode run "fix the bug"` on the CLI through project bootstrapping, session
creation, provider selection, permission gating, model streaming, and final
persistence. It covers the boundary crossings between the CLI runtime, the
project/instance layer, the session system, the provider system, the permission
system, and the Bus event layer.

Understanding this path matters because OpenCode separates concerns sharply: the
CLI initiates but does not own state; the session system owns durable state but
does not choose models; the provider system chooses models but does not gate
tool calls; the permission system gates tool calls but does not stream responses.
A defect that surfaces at any one of these layers may have its root cause two or
three boundaries earlier.

## Systems Involved

| System | Contribution |
| --- | --- |
| [CLI Runtime](../entities/cli-runtime.md) | Parses CLI arguments, sets up yargs commands, calls bootstrap helpers |
| [Project and Instance System](../entities/project-and-instance-system.md) | Creates or reuses the per-directory `InstanceContext`, resolves project metadata |
| [Session System](../entities/session-system.md) | Creates `Session.Info` rows in SQLite, selects prompt variant, manages message lifecycle |
| [Provider System](../entities/provider-system.md) | Selects provider and model from config, authenticates, constructs AI SDK model object |
| [Permission System](../entities/permission-system.md) | Evaluates `Permission.Rule` sets, emits `permission.asked` events, waits for `permission.replied` |
| [Bus System](../entities/storage-and-sync.md) | Pub/sub layer that propagates session, message, and permission events to all connected clients |

## Step-by-Step Flow

### 1. CLI Entry Point

`index.ts` registers all yargs commands including `RunCommand`. The user's
invocation is parsed and `RunCommand.handler` receives the prompt string and
optional flags: `--model`, `--provider`, `--no-approval`. No session state is
created here; this step only prepares the invocation context.

### 2. Bootstrap

`RunCommand` calls the project-scoped bootstrap helper (`cli/bootstrap.ts`).
The helper resolves the current working directory via `path.resolve(process.cwd())`
and invokes `Instance.provide({ directory })`. This call enters the Node Async
Local Storage scope that threads `InstanceContext` through all downstream calls
without explicit argument passing.

### 3. Instance Resolution

`Instance.provide` checks the module-level `cache: Map<string, Promise<InstanceContext>>`.

On a **cache hit**, the existing `InstanceContext` is returned immediately — no
DB query occurs.

On a **cache miss**, `boot({ directory })` is called:
- `Project.fromDirectory(directory)` queries `ProjectTable` by matching the
  directory prefix to known project worktrees.
- If no project row exists, one is upserted with a generated `ProjectID` (ULID)
  and the directory as its `worktree`.
- The git worktree root is resolved by walking parent directories for `.git`
  (falls back to `"/"` for non-git directories).
- `InstanceContext = { directory, worktree, project: Project.Info }` is constructed.
- The result is stored in the cache via `track(directory, context)` and exposed
  through `Context.create<InstanceContext>("instance")`.

### 4. Session Creation

The session layer calls `Session.create()`:
- A `SessionID` (ULID) is generated.
- A URL-safe `slug` is computed via the `Slug` utility.
- A row is inserted into `SessionTable` (Drizzle/SQLite) via `toRow(info)`.

Fields written at creation time:
- `id`: the new `SessionID`
- `slug`: URL-safe identifier
- `project_id`: from `InstanceContext.project.id`
- `workspace_id`: `null` for local sessions
- `directory`: from `InstanceContext.directory`
- `title`: produced by `createDefaultTitle(false)` → `"New session - " + new Date().toISOString()`
- `version`: current schema version string
- `time_created`: current Unix timestamp (ms)

The `isDefaultTitle(title)` predicate later recognises auto-generated titles
by testing against the regex:
`^(New session - |Child session - )\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$`

### 5. Prompt Variant Selection

`SessionPrompt` in `session/prompt.ts` inspects the session state:
- Is `parentID` set? (Is this a child/compaction session?)
- Is a `summary` object present on the parent `Session.Info`?
- What system-prompt flags does the config enable?

For child sessions, `SessionPrompt` reads the parent's `summary` object and
injects `summary.additions`, `summary.deletions`, `summary.files`, and
`summary.diffs` as a condensed history preamble. This lets the model start with
context without replaying thousands of prior-turn tokens.

### 6. Provider and Model Selection

`Provider.get(providerID, modelID)` is called:
1. Reads the provider config entry from `Config` (keyed by `ProviderID`).
2. Resolves credentials via `Auth.get(providerID)` — checks environment variables,
   then OS keychain, then stored config, in that order.
3. Constructs the AI SDK adapter:
   - `createAnthropic({ apiKey })` for Anthropic
   - `createOpenAI({ apiKey, baseURL })` for OpenAI and compatible APIs
   - `createAmazonBedrock({ region, credentials })` for AWS Bedrock
   - `createGoogle({ apiKey })` for Google AI
4. Returns a `LanguageModelV3` object carrying `modelId`, `provider`, and
   capability flags: `supportsToolCalls`, `supportsImageInput`, `supportsObjectGeneration`.

### 7. Tool Registry Assembly

`ToolRegistry.Interface.tools({ providerID, modelID }, agent?)` assembles the
tool list for this turn:
- Reads all registered `Tool.Info` entries from the built-in catalog:
  `tool/bash.ts` (`"bash"`), `tool/read.ts` (`"read"`), `tool/write.ts` (`"write"`),
  `tool/edit.ts` (`"edit"`), `tool/glob.ts` (`"glob"`), `tool/grep.ts` (`"grep"`),
  `tool/task.ts` (`"task"`), `tool/webfetch.ts` (`"webfetch"`), plus any tools
  contributed by plugins in the pre-turn hook.
- Calls `init(ctx?)` lazily on each `Tool.Info` to obtain the `Tool.Def`.
- Filters against capability flags: `supportsToolCalls = false` → empty list;
  `supportsImageInput = false` → image-type tools excluded.
- Returns `Tool.Def[]` with JSON Schema for each parameter set.

### 8. Plugin Pre-Turn Hook

`Plugin.Service.trigger("beforeTurn", input, output)` fires:
- Iterates all loaded `Hooks` objects that implement `beforeTurn`.
- Built-in plugins (`CodexAuthPlugin`, `CopilotAuthPlugin`, `GitlabAuthPlugin`,
  `PoeAuthPlugin`) inject or refresh auth tokens at this point.
- External plugins loaded by `PluginLoader` may add tools to the output tool
  list or inject context strings into the prompt preamble.
- If any plugin throws, `trigger` propagates the error and the turn is aborted.

### 9. Model Streaming

The session calls the AI SDK streaming interface (`streamText`) with:
- `model`: the `LanguageModelV3` from step 6
- `messages`: assembled `MessageV2.WithParts[]` in AI SDK format
- `system`: the system prompt string from `SessionPrompt`
- `tools`: the `Tool.Def[]` array serialized to JSON Schema
- `abortSignal`: tied to the session's cancel mechanism

The model streams `TextPart` and `ToolCallPart` chunks back incrementally.

### 10. Tool Call Permission Gate

For each `ToolCallPart` received (`{ toolName, args, callId }`), the tool's
`execute` function calls `ctx.ask(permissionInput)`. This invokes
`Permission.Interface.ask`, which calls `Permission.evaluate(ruleset, permissionName, pattern)`:
- Walks the active `Ruleset` with `findLast` (later rules override earlier ones).
- Matches `rule.permission` against `permissionName` and `rule.pattern` against
  `pattern` via `Wildcard.match()`.
- Returns `Action`:
  - `"allow"` → proceeds immediately to tool execution (step 12).
  - `"deny"` → raises `Permission.DeniedError` with matching rules; tool blocked.
  - `"ask"` (or no match) → proceeds to permission request (step 11).

### 11. Permission Request Raised and Awaited

A `Permission.Request` is constructed and persisted to `PermissionTable`:
- `id`: new `PermissionID` (ULID)
- `sessionID`: current session's ID
- `permission`: name string (e.g., `"bash"`)
- `patterns`: resource patterns (e.g., `["/etc/hosts"]`)
- `always`: advisory list of patterns the tool suggests auto-approving
- `metadata`: display metadata for the UI
- `tool.messageID` and `tool.callID`: correlation to the blocked `ToolCallPart`

`Bus.publish(Permission.Event.Asked, request)` fires. The SSE frame
`{ type: "permission.asked", payload: request }` is delivered to all clients.
Tool execution pauses in an Effect `Deferred` awaiting `Permission.Event.Replied`.

When a client replies via `POST /permission/reply`:
- `"once"` → unblocks this call only; no persistent record written.
- `"always"` → writes `Permission.Approval { projectID, patterns }` to DB;
  appends to in-memory `approved` ruleset; unblocks the call.
- `"reject"` → raises `Permission.RejectedError`; cascades to cancel all pending
  requests from the same `sessionID`.

### 12. Tool Execution

The permitted tool function runs with `Tool.Context`:
- `sessionID`, `messageID`, `agent`: identifiers
- `abort`: `AbortSignal` fired when user cancels
- `callID`: matches `ToolCallPart.callId`
- `messages`: full `MessageV2.WithParts[]` history
- `metadata(input)`: pushes `{ title?, metadata? }` UI updates mid-execution
- `ask(input)`: nested permission callback for sub-operations

Returns `{ title, metadata, output, attachments? }`. The result is wrapped into
`ToolResultPart { toolCallId, result: unknown }` and appended to message history.

### 13. Response Streaming to Clients

After each chunk (text, tool call, tool result):
- `Bus.publish(Message.Event.Updated, message)` — delivers the updated
  `MessageV2.WithParts` to all SSE subscribers.
- `Bus.publish(Session.Event.Updated, session)` — delivers updated `Session.Info`.
- SSE frames are serialized JSON: `data: { "type": "message.updated", "payload": {...} }\n\n`

### 14. Loop Until Stop

Steps 9–13 repeat until the model emits a stop signal:
- `finish_reason: "stop"` — normal end of turn.
- `finish_reason: "max_tokens"` — context limit; triggers compaction.
- `finish_reason: "stop_sequence"` — explicit stop token matched.

Multiple `ToolCallPart` items may be emitted per turn; each follows the full
permission-gate-execute-result cycle. The final assistant message is written to
`MessageTable` via the Drizzle insert.

### 15. Session Update

`Session.update()` writes back to `SessionTable` via `toRow(info)`:
- `time_updated`: current Unix ms timestamp
- `summary_additions`, `summary_deletions`, `summary_files`, `summary_diffs`:
  populated if compaction ran during this turn
- `time_compacting`: set at compaction start; preserved as record of when it ran
- `revert`: set if a restore checkpoint was captured during the turn

### 16. Plugin Post-Turn Hook

`Plugin.Service.trigger("afterTurn", input, output)` fires. The `output` object
includes final `MessageV2.WithParts`, token usage (`LanguageModelV2Usage`), and
`finish_reason`. Plugins may:
- Record token usage to an external metrics system
- Update file-index or embedding caches
- Post summaries to Slack or another external system
- Trigger follow-on automations (e.g., run test suite after a code change)

If any plugin throws, the turn is marked complete but side effects are lost.

## Data at Each Boundary

| Boundary | Data Crossing | Key Types |
| --- | --- | --- |
| CLI → Instance | Working directory path | `{ directory: string }` from `path.resolve(process.cwd())` |
| Instance → Session | Full instance context | `InstanceContext { directory, worktree, project: Project.Info }` |
| Instance → Session | Project identity | `project.id: ProjectID` written to `session.projectID` |
| Session → Provider | Model selection | `{ providerID: ProviderID, modelID: ModelID }` from `Config`; resolved `Auth` credentials |
| Provider → AI SDK | Model object | `LanguageModelV3` with `modelId`, `provider`, `supportsToolCalls`, `supportsImageInput` flags |
| AI SDK → Session | Streamed chunks | `TextPart { type: "text", text: string }`, `ToolCallPart { type: "tool-call", toolName, args, callId }` |
| Session → Permission | Tool call details | `permissionName: string`, `patterns: string[]`, `metadata: Record<string, any>`, `always: string[]` |
| Permission → Bus | Pending request | `Permission.Request { id, sessionID, permission, patterns, always, metadata, tool: { messageID, callID } }` |
| Bus → Clients | SSE event | `{ type: "permission.asked", payload: Permission.Request }` as SSE frame |
| Client → Bus | User reply | `Permission.Event.Replied { sessionID, requestID, reply: "once" \| "always" \| "reject" }` |
| Permission → Tool | Execution unblocked | Effect `Deferred` resolved; `ctx.ask()` returns `void` |
| Tool → Session | Execution result | `ToolResultPart { toolCallId: string, result: unknown }` appended to `MessageV2.WithParts` |
| Session → Bus | State change | `Session.Event.Updated` with `Session.Info`; `Message.Event.Updated` with `MessageV2.WithParts` |
| Bus → Clients | SSE stream | Serialized `BusEvent` JSON frames consumed by `EventSource` on client side |

## Failure Points

| Stage | What Can Fail | Mechanism | Observable Symptom |
| --- | --- | --- | --- |
| Instance boot | `Project.fromDirectory` cannot find git root or config | Exception thrown in `boot()` | Bootstrap error before session is created; CLI exits with stack trace |
| Instance boot | Directory does not exist on filesystem | `fs.stat` failure | `ENOENT` error; session never created |
| Session creation | SQLite write fails (disk full, locked DB, schema mismatch) | Drizzle insert rejects | SQL error thrown; CLI exits; no session row in DB |
| Session creation | `slug` collision (rare ULID collision) | Unique constraint violation on `slug` column | Retry may succeed; unhandled crash on persistent collision |
| Provider selection | Missing or invalid API key | `Auth.get` returns null or throws | `NamedError` with auth failure; model never called |
| Provider selection | Model ID not found in provider's list | AI SDK rejects unknown `modelId` | `NoSuchModelError`; turn aborted before model called |
| Provider selection | Network unreachable at provider endpoint | HTTP connect timeout in AI SDK | Stream never starts; session frozen |
| Permission gate | No rule matches and no client connected | Effect `Deferred` never resolved | Tool call blocks indefinitely; session appears frozen |
| Permission gate | Client sends `"reject"` reply | `Permission.RejectedError` raised | Tool skipped; `RejectedError` propagated; model receives error result |
| Permission gate | Client disconnects before replying | `Deferred` orphaned | Turn hangs until server restart |
| Model streaming | Network error mid-stream | AI SDK stream aborts | Partial message saved; retry may restart turn |
| Model streaming | Context window exceeded | `finish_reason: "length"` from AI SDK | Compaction triggered; child session created |
| Tool execution | Tool throws at runtime | Uncaught exception in `Tool.Def.execute` | Error propagated as `ToolResultPart`; model sees the error text |
| SSE publish | No subscribers (all clients disconnected) | `Bus.publish` iterates empty set | Events emitted into void; state still persisted to SQLite |
| Plugin pre-turn | Plugin throws or hangs | `trigger` propagates exception | Turn never starts; error surfaced to session layer |
| Plugin post-turn | Plugin throws | `trigger` propagates exception | Turn marked complete but side effects lost |

## Source Evidence

| File | Function / Symbol | Why It Matters |
| --- | --- | --- |
| `packages/opencode/src/index.ts` | `RunCommand` registration | Root entry point; registers all CLI commands |
| `packages/opencode/src/cli/cmd/run.ts` | `RunCommand.handler` | Calls bootstrap, creates session, starts prompt loop |
| `packages/opencode/src/project/instance.ts` | `Instance.provide`, `boot`, `track`, `cache` | Per-directory context cache and boot sequence |
| `packages/opencode/src/project/project.ts` | `Project.fromDirectory` | Resolves `Project.Info` from filesystem directory |
| `packages/opencode/src/session/index.ts` | `Session.create`, `Session.fromRow`, `Session.toRow`, `createDefaultTitle`, `isDefaultTitle` | Session row lifecycle; title prefix constants |
| `packages/opencode/src/session/prompt.ts` | `SessionPrompt` (variant selector) | Selects system prompt; injects parent summary |
| `packages/opencode/src/provider/provider.ts` | `Provider.get`, `createAnthropic`, `createOpenAI` | AI SDK adapter construction; auth resolution |
| `packages/opencode/src/tool/registry.ts` | `ToolRegistry.Interface.tools` | Tool list assembly and capability filtering |
| `packages/opencode/src/permission/index.ts` | `Permission.Rule`, `Permission.Request`, `Permission.Reply`, `Permission.Event.Asked`, `Permission.Event.Replied`, `DeniedError`, `RejectedError` | Full permission type surface |
| `packages/opencode/src/permission/evaluate.ts` | `evaluate(ruleset, permission, pattern)` | Walks `Ruleset` with `findLast`; returns `Action` |
| `packages/opencode/src/plugin/index.ts` | `Plugin.Service.trigger`, `Plugin.Interface`, `TriggerName` | Plugin hook orchestration |
| `packages/opencode/src/bus/index.ts` | `Bus.publish`, `Bus.subscribe` | SSE fanout to all connected clients |

## See Also

- [Session System](../entities/session-system.md)
- [Provider System](../entities/provider-system.md)
- [Permission System](../entities/permission-system.md)
- [Tool System](../entities/tool-system.md)
- [Plugin System](../entities/plugin-system.md)
- [Context Compaction and Session Recovery](context-compaction-and-session-recovery.md)
- [Provider Tool Plugin Interaction Model](provider-tool-plugin-interaction-model.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
