# Provider Tool Plugin Interaction Model

## Overview

This synthesis traces how providers, tools, and plugins combine during a single
agent turn. The three systems do not interact directly with each other; they are
orchestrated by the session layer, which calls each in a defined sequence.
Plugins fire at hook points before and after the turn. The provider supplies the
model. The tool registry supplies the tool list filtered by model capability.
The permission system gates each tool call. The loop repeats until the model
stops.

Understanding the interaction model matters because changes to any one of these
three systems ripple into the turn loop. A new plugin hook that modifies the
tool list changes what the model can call. A new permission rule that always
denies a tool silently skips tool calls the model expects to succeed. A provider
capability flag that marks a model as not supporting tool use removes the entire
tool list from that model's turns. None of these effects are visible at the
individual system layer; they only become visible when the full turn sequence is
examined.

## Systems Involved

| System | Contribution |
| --- | --- |
| [Plugin System](../entities/plugin-system.md) | `Plugin.Interface.trigger` at pre-turn and post-turn hook points; built-in auth plugins; external plugin loading |
| [Provider System](../entities/provider-system.md) | Provider selection from config, auth resolution, `LanguageModelV3` construction |
| [Tool System](../entities/tool-system.md) | Tool registry assembly; capability-based filtering; plugin tool merging |
| [Permission System](../entities/permission-system.md) | `Permission.Rule` evaluation; `Permission.Event.Asked` / `Permission.Event.Replied` lifecycle |
| [Session System](../entities/session-system.md) | Turn loop orchestration; message history management; Bus event publication |

## Step-by-Step Flow

### 1. Session Initiates a Turn

The session layer has:
- The current `MessageV2.WithParts[]` message history
- The active `Session.Info` (with `id`, `projectID`, `directory`, `parentID?`,
  `permission?`, `time`)
- The configured `providerID` and `modelID` from `Config`
- A new `MessageID` (ULID) generated for the assistant message of this turn

No model call has been made yet. All decisions for this turn are made in the
following steps.

### 2. Plugin Pre-Turn Hook Fires

`Plugin.Service.trigger("beforeTurn", input, output)` is called.

The `trigger` method on `Plugin.Interface` iterates all loaded `Hooks` objects
and calls the `beforeTurn` hook on each that implements it.

**Built-in plugins** that may fire here:
- `CodexAuthPlugin` — injects Codex auth token if Codex provider is active
- `CopilotAuthPlugin` — refreshes GitHub Copilot OAuth token
- `GitlabAuthPlugin` — injects GitLab personal access token
- `PoeAuthPlugin` — injects Poe API key

**External plugins** loaded by `PluginLoader` from the plugin directory may:
- Add `Tool.Info` entries to the output tool list
- Inject additional context strings into the prompt preamble
- Modify the effective `providerID` or `modelID` in the output config
- Set or refresh auth tokens for the current provider

If any plugin's `beforeTurn` implementation throws synchronously or rejects a
Promise, `trigger` propagates the error to the session layer and the turn is
aborted before the model is called.

### 3. Provider Selection

`Provider.get(providerID, modelID)` is called (using the possibly-modified
`providerID`/`modelID` from the plugin pre-turn output):

1. Reads the provider config entry from `Config` (keyed by `ProviderID`).
2. Calls `Auth.get(providerID)` to resolve credentials:
   - Checks environment variables first (e.g., `ANTHROPIC_API_KEY`)
   - Then OS keychain
   - Then stored config file
3. Constructs the AI SDK adapter:
   - `createAnthropic({ apiKey })` for Anthropic Claude models
   - `createOpenAI({ apiKey, baseURL })` for OpenAI and compatible APIs
   - `createAmazonBedrock({ region, credentials })` for AWS Bedrock
   - `createGoogle({ apiKey })` for Google AI / Gemini
4. Returns a `LanguageModelV3` carrying:
   - `modelId: string`
   - `provider: string`
   - `supportsToolCalls: boolean`
   - `supportsImageInput: boolean`
   - `supportsObjectGeneration: boolean`

### 4. Tool Registry Assembly

`ToolRegistry.Interface.tools({ providerID, modelID }, agent?)` assembles the
tool list:

**Sources read:**
- Built-in tools from the catalog:
  - `tool/bash.ts` → `"bash"` (shell command execution)
  - `tool/read.ts` → `"read"` (file reading)
  - `tool/write.ts` → `"write"` (file writing)
  - `tool/edit.ts` → `"edit"` (targeted file editing)
  - `tool/glob.ts` → `"glob"` (file pattern matching)
  - `tool/grep.ts` → `"grep"` (content search)
  - `tool/task.ts` → `"task"` (spawn sub-agent)
  - `tool/webfetch.ts` → `"webfetch"` (HTTP fetch)
  - Plus additional built-in tools as defined in the registry
- Plugin-contributed `Tool.Info` entries injected in step 2

**Initialization:**
- `Tool.Info.init(ctx?)` is called lazily on each entry to obtain `Tool.Def`.
- `Tool.define(id, init)` wraps the init with Zod argument validation and
  output truncation via `Truncate.output()`.

**Capability filtering:**
- `supportsToolCalls = false` → return empty array
- `supportsImageInput = false` → exclude image-type tools

**Result:** `Tool.Def[]` with JSON Schema for each parameter set, ready for
the AI SDK call.

### 5. Model Is Called

The session calls the AI SDK streaming interface (`streamText`) with:
- `model`: the `LanguageModelV3` from step 3
- `messages`: the assembled `MessageV2.WithParts[]` in AI SDK format
- `system`: the system prompt from `SessionPrompt` (includes parent summary
  preamble for child sessions)
- `tools`: the `Tool.Def[]` array, each serialized to JSON Schema with
  `name`, `description`, and `parameters: JSONSchema7`
- `abortSignal`: tied to the session's cancel mechanism

The model begins streaming chunks back incrementally.

### 6. Text Parts Streamed

As `TextPart` chunks arrive (`{ type: "text", text: string }`):
- The session layer appends them to the in-progress `MessageV2.WithParts`
  assistant message.
- `Bus.publish(Message.Event.Updated, message)` fires.
- All connected clients receive the SSE frame and update their rendered output.

Text parts and tool call parts may be interleaved; the streaming loop handles
both in the same iteration.

### 7. Tool Call Part Arrives

The model emits a `ToolCallPart`:
```typescript
{ type: "tool-call", toolName: string, args: Record<string, any>, callId: string }
```

The session layer pauses processing for that specific tool call (other parts
continue streaming) and invokes the permission system via the tool's
`ctx.ask()` callback.

### 8. Permission Rule Evaluation

`ctx.ask(permissionInput)` calls `Permission.Interface.ask`, which calls
`Permission.evaluate(ruleset, permissionName, pattern)`:

The `ruleset` is the merged result of:
- Config-level `Permission.Ruleset` (from `Config`)
- Session-level `session.permission` override (from `Session.Info.permission`)
- In-memory `approved` list from `"always"` replies in this session

`evaluate` walks the ruleset with `findLast` (later rules override earlier):
- Matches `rule.permission` against `permissionName` via `Wildcard.match()`
- Matches `rule.pattern` against `pattern` via `Wildcard.match()`
- Returns the first matching rule's `action`

**Action outcomes:**
- `"allow"` → `ctx.ask()` returns `void` immediately; skip to step 10
- `"deny"` → raises `Permission.DeniedError` with matching ruleset; tool blocked
- `"ask"` (or no matching rule) → proceed to step 9

### 9. `Permission.Event.Asked` Broadcast and Await

A `Permission.Request` is constructed and persisted to `PermissionTable`:
```typescript
{
  id:         PermissionID  // new ULID
  sessionID:  Session.Info.id
  permission: string        // e.g., "bash"
  patterns:   string[]      // e.g., ["rm -rf /tmp/build"]
  metadata:   Record<string, any>  // tool display metadata
  always:     string[]      // patterns the tool suggests auto-approving
  tool: {
    messageID: MessageID
    callID:    string       // matches ToolCallPart.callId
  }
}
```

`Bus.publish(Permission.Event.Asked, request)` fires. The SSE frame:
```
{ "type": "permission.asked", "payload": { ...request } }
```
is delivered to every connected client. Tool execution pauses in an Effect
`Deferred` awaiting `Permission.Event.Replied`.

When a client replies via `POST /permission/reply` with
`Permission.ReplyInput { requestID, reply, message? }`:

- **`"once"`** — unblocks this call only; no persistent record written;
  `ctx.ask()` returns `void`.
- **`"always"`** — writes `Permission.Approval { projectID, patterns }` to
  `PermissionTable`; appends `always` patterns to in-memory `approved` ruleset;
  `ctx.ask()` returns `void`. Future calls matching the same pattern are
  automatically allowed for the lifetime of the project.
- **`"reject"`** — raises `Permission.RejectedError`:
  `"The user rejected permission to use this specific tool call."`;
  cascades to cancel all other pending `Permission.Request`s from the same
  `sessionID`.

A `"reject"` reply with a feedback `message` string raises
`Permission.CorrectedError` instead, which includes the feedback text so the
model can adjust its approach.

### 10. Tool Executes

The permitted tool function (`Tool.Def.execute(args, ctx)`) runs with
`Tool.Context`:
- `sessionID`, `messageID`, `agent`: turn identifiers
- `abort`: `AbortSignal` fired when user cancels the turn
- `callID`: matches `ToolCallPart.callId` for correlation
- `messages`: full `MessageV2.WithParts[]` history for context-aware tools
- `metadata(input)`: pushes `{ title?, metadata? }` UI updates mid-execution
- `ask(input)`: nested permission callback for sub-operations within the tool

The tool returns:
```typescript
{ title: string, metadata: M, output: string, attachments?: MessageV2.FilePart[] }
```

### 11. Tool Result Fed Back to Model

The result is wrapped in a `ToolResultPart`:
```typescript
{ type: "tool-result", toolCallId: string, result: unknown }
```

If `output` exceeds the truncation threshold, `Truncate.output()` writes the
full output to a temp file and returns a pointer in `metadata.outputPath`; the
model receives the truncated version.

`Bus.publish(Message.Event.Updated, message)` fires again, delivering the
tool result to all clients via SSE.

### 12. Steps 6–11 Repeat

The model may emit multiple `ToolCallPart` items in a single turn, interleaved
with `TextPart` chunks. Each tool call follows the same
permission-gate-execute-result cycle independently. The streaming loop
continues until the model emits a stop signal.

### 13. Model Stops

The model emits a stop signal:
- `finish_reason: "stop"` — normal end of turn
- `finish_reason: "max_tokens"` — context limit; triggers compaction
- `finish_reason: "stop_sequence"` — explicit stop token matched

The session layer finalizes the `MessageV2.WithParts` assistant message and
writes it to `MessageTable` via the Drizzle insert. If `finish_reason` is
`"max_tokens"`, the compaction flow in
[Context Compaction and Session Recovery](context-compaction-and-session-recovery.md)
is triggered.

### 14. Plugin Post-Turn Hook Fires

`Plugin.Service.trigger("afterTurn", input, output)` is called.

The `output` object available to post-turn hooks includes:
- The final `MessageV2.WithParts`
- Token usage: `LanguageModelV2Usage { promptTokens, completionTokens, totalTokens }`
- The `finish_reason` string

Plugins may:
- Record token usage to an external metrics system
- Update file-index or embedding caches
- Post a summary or result to Slack or another external system
- Trigger follow-on automations (e.g., run the test suite after a code change)

If any plugin's `afterTurn` throws, the turn is marked complete but side effects
are lost. The error is logged but not surfaced to the user as a turn failure.

### 15. Bus Publishes Final Events

`Bus.publish(Session.Event.Updated, session)` fires with the updated
`Session.Info` (including refreshed `time.updated` and any new `summary` fields
if compaction ran). The turn is complete.

## Data at Each Boundary

| Boundary | Data Crossing | Key Types |
| --- | --- | --- |
| Plugin pre-turn → session | Modified turn config | Tool list additions (`Tool.Info[]`), context strings, possibly updated `providerID`/`modelID` |
| Session → `Provider.get` | Provider identity | `providerID: ProviderID`, `modelID: ModelID`, resolved `Auth` credentials (API key) |
| `Provider.get` → AI SDK | Model object | `LanguageModelV3 { modelId, provider, supportsToolCalls, supportsImageInput }` |
| Tool registry → AI SDK call | Tool definitions | `Tool.Def[]` serialized as `{ name, description, parameters: JSONSchema7 }` |
| AI SDK → session (text) | Streamed text chunk | `TextPart { type: "text", text: string }` |
| AI SDK → session (tool call) | Tool invocation | `ToolCallPart { type: "tool-call", toolName, args: Record<string,any>, callId }` |
| Session → `ctx.ask()` | Permission request input | `permissionName: string`, `patterns: string[]`, `metadata`, `always: string[]` |
| `ctx.ask()` → Permission | Full ask input | `Permission.AskInput` (partial `Request` + `ruleset: Ruleset`) |
| Permission → Bus (`Event.Asked`) | Pending request broadcast | `Permission.Request { id, sessionID, permission, patterns, always, metadata, tool }` |
| Bus → all clients (SSE) | Permission event | `{ type: "permission.asked", payload: Permission.Request }` |
| Client → Hono REST | User reply | `POST /permission/reply` with `Permission.ReplyInput { requestID, reply, message? }` |
| Bus → session (`Event.Replied`) | Reply unblocks Deferred | `{ sessionID, requestID, reply: "once" \| "always" \| "reject" }` |
| `"always"` reply → DB | Persistent approval | `Permission.Approval { projectID, patterns }` to `PermissionTable` |
| Tool function → session | Execution result | `{ title, metadata: M, output: string, attachments? }` |
| Session → AI SDK (tool result) | Result for next model call | `ToolResultPart { type: "tool-result", toolCallId, result: unknown }` |
| Plugin post-turn → external | Side effects | `LanguageModelV2Usage`, `MessageV2.WithParts`, `finish_reason` |

## Failure Points

| Stage | What Can Fail | Mechanism | Observable Symptom |
| --- | --- | --- | --- |
| Plugin pre-turn | Plugin throws synchronously or rejects Promise | `trigger` propagates exception | Turn never starts; error surfaced to session; model not called |
| Plugin pre-turn | Plugin hangs (infinite loop, awaits external) | `trigger` awaits Promise that never resolves | Turn hangs indefinitely; session frozen from client perspective |
| Plugin tool registration | Plugin contributes `Tool.Info` with invalid schema | `Tool.Def.parameters` Zod parse fails at first use | Plugin tool absent from model's tool list; silent failure |
| Provider selection | API key missing from environment and keychain | `Auth.get` returns null | AI SDK throws auth error; turn aborted before model called |
| Provider selection | Model ID not found in provider's list | AI SDK rejects unknown `modelId` | `NoSuchModelError` thrown; turn aborted |
| Provider selection | Provider endpoint unreachable | HTTP connect timeout | Stream never starts; session frozen |
| Tool registry | `Tool.Info.init()` throws during lazy initialization | Exception in `init` | That tool absent from model's tool list |
| Tool capability filter | `supportsToolCalls` flag incorrectly false | All tools filtered out | Model receives empty tool list; text-only turn |
| Permission rule evaluation | `Ruleset` empty and no client connected | Effect `Deferred` never resolved | Tool call blocks indefinitely |
| Permission request | Client crashes before replying | `Permission.Event.Replied` never published | Turn hangs until server restart |
| Permission request | `PermissionTable` insert fails | Drizzle insert throws | Permission not persisted; lost on server restart |
| `"always"` approval write | `PermissionTable` insert fails | Drizzle insert throws | Approval not persisted; user prompted again next turn |
| Tool execution | Tool throws at runtime | Uncaught exception in `Tool.Def.execute` | Error as `ToolResultPart`; model may retry or surface error |
| Tool execution | `abort` signal fired mid-execution | `AbortSignal.aborted` true during async operation | Tool should check `abort`; if not, continues as zombie |
| Output truncation | `Truncate.output()` temp file write fails | `fs.writeFile` throws | Model receives oversized output; may exceed context window |
| Model stop: max tokens | Context window exceeded | `finish_reason: "max_tokens"` | Compaction triggered; child session created |
| Plugin post-turn | Plugin throws after turn complete | `trigger` propagates; turn already done | Side effects lost; not user-visible |
| Bus publish (tool result) | All SSE connections closed between call and result | `Bus.publish` iterates empty subscriber set | Tool result lost for clients; DB updated; must manually refresh |

## Source Evidence

| File | Function / Symbol | Why It Matters |
| --- | --- | --- |
| `packages/opencode/src/plugin/index.ts` | `Plugin.Interface`, `Plugin.Service`, `trigger(name, input, output)`, `TriggerName`, `Hooks` | Plugin hook orchestration; `beforeTurn`/`afterTurn` trigger points |
| `packages/opencode/src/plugin/loader.ts` | `PluginLoader` | External plugin loading and resolution |
| `packages/opencode/src/provider/provider.ts` | `Provider.get`, `createAnthropic`, `createOpenAI`, `createAmazonBedrock`, `createGoogle` | AI SDK adapter construction; auth resolution via `Auth.get` |
| `packages/opencode/src/provider/schema.ts` | `ProviderID`, `ModelID` branded types | Type-safe provider and model identifiers |
| `packages/opencode/src/tool/registry.ts` | `ToolRegistry.Interface.tools`, `ids`, `named` | Tool list assembly; capability-based filtering; plugin tool merging |
| `packages/opencode/src/tool/tool.ts` | `Tool.Def`, `Tool.Info`, `Tool.Context`, `Tool.define`, `Truncate.output` | Core tool types; `ctx.ask()` integration; output truncation |
| `packages/opencode/src/permission/index.ts` | `Permission.Rule`, `Permission.Ruleset`, `Permission.Request`, `Permission.Reply`, `Permission.Approval`, `Permission.Event.Asked`, `Permission.Event.Replied`, `Permission.AskInput`, `Permission.ReplyInput`, `DeniedError`, `RejectedError`, `CorrectedError` | Full permission type surface; all error types |
| `packages/opencode/src/permission/evaluate.ts` | `evaluate(ruleset, permission, pattern)` | `findLast` walk over `Ruleset`; `Wildcard.match` for glob matching |
| `packages/opencode/src/session/index.ts` | Turn loop orchestration, `MessageV2.WithParts` assembly, `Bus.publish` calls | Session-level turn orchestration; message history; Bus events |
| `packages/opencode/src/session/prompt.ts` | `SessionPrompt` (variant selector) | System prompt construction; summary injection for child sessions |

## See Also

- [Provider System](../entities/provider-system.md)
- [Tool System](../entities/tool-system.md)
- [Plugin System](../entities/plugin-system.md)
- [Permission System](../entities/permission-system.md)
- [Provider Agnostic Model Routing](../concepts/provider-agnostic-model-routing.md)
- [Plugin Driven Extensibility](../concepts/plugin-driven-extensibility.md)
- [Request to Session Execution Flow](request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
