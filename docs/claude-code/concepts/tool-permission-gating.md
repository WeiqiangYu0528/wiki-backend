# Tool Permission Gating

## Overview
Tool Permission Gating is the mechanism by which every individual tool call is checked against the permission model before execution. While the [Permission Model](./permission-model.md) defines the rules and modes, Tool Permission Gating is the runtime enforcement layer -- the code path that sits between the assistant's tool_use request and the actual tool execution.

## Mechanism

### The `CanUseToolFn` Hook
The central abstraction is the `CanUseToolFn` type, defined in `hooks/useCanUseTool.tsx`:

```typescript
type CanUseToolFn<Input> = (
  tool: ToolType,
  input: Input,
  toolUseContext: ToolUseContext,
  assistantMessage: AssistantMessage,
  toolUseID: string,
  forceDecision?: PermissionDecision<Input>,
) => Promise<PermissionDecision<Input>>
```

This function is called for every tool invocation. It returns a `PermissionDecision` -- one of `allow`, `deny`, or `ask`. The `forceDecision` parameter lets callers override the normal check (used during SDK replay).

### `useCanUseTool` React Hook
In the interactive REPL, `useCanUseTool` is a React hook that wraps the permission pipeline and connects it to the UI for prompting:

1. **Create permission context**: `createPermissionContext()` builds a context object with the tool, input, message ID, and queue operations for UI prompts.
2. **Check abort**: If the session is aborted, resolve immediately.
3. **Call `hasPermissionsToUseTool`**: This is the core rule-evaluation function from `utils/permissions/permissions.ts`. If `forceDecision` is provided, it is used directly instead.
4. **Handle the result by behavior**:

#### `allow` Path
- If the classifier (auto mode) approved, record the classifier approval via `setYoloClassifierApproval`.
- Log the decision as `{decision: "accept", source: "config"}`.
- Resolve with the allow decision, passing through any `updatedInput`.

#### `deny` Path
- Log the decision as `{decision: "reject", source: "config"}`.
- If denied by the auto-mode classifier, record the denial for UX tracking (`recordAutoModeDenial`) and push an inline notification ("tool_name denied by auto mode").
- Resolve with the deny decision.

#### `ask` Path
This is the most complex branch, with multiple sub-handlers tried in order:

1. **Coordinator handler** (`handleCoordinatorPermission`): If `awaitAutomatedChecksBeforeDialog` is set, try automated approval (e.g., from a coordinator agent). If it returns a decision, use it.
2. **Swarm worker handler** (`handleSwarmWorkerPermission`): If running as a swarm worker, delegate the permission decision to the parent agent.
3. **Speculative bash classifier** (feature-gated): For bash commands, check if a speculative classifier result is already available. If it matched with high confidence, auto-approve without prompting. This races the classifier against a 2-second timeout.
4. **Interactive handler** (`handleInteractivePermission`): Fall through to showing the user a permission prompt in the REPL UI. Also supports bridge callbacks (remote IDE integration) and channel callbacks (Kairos).

### `hasPermissionsToUseTool` -- The Rule Pipeline
Located in `utils/permissions/permissions.ts`, this function implements a strict priority pipeline:

1. **Deny rules** (step 1a): Check if the entire tool is denied via `getDenyRuleForTool`. If matched, immediately deny.
2. **Ask rules** (step 1b): Check if the entire tool has an always-ask rule via `getAskRuleForTool`. Exception: if Bash is sandboxed and `autoAllowBashIfSandboxed` is enabled, fall through.
3. **Tool-specific validation** (step 1c): Call `tool.checkPermissions(parsedInput, context)` -- each tool implements its own content-aware permission logic (e.g., BashTool checks individual commands against allow/deny patterns).
4. **Tool deny** (step 1d): If the tool's own `checkPermissions` returned `deny`, honor it.
5. **User interaction required** (step 1e): Some tools require user interaction even in bypass mode.
6. **Content-specific ask rules** (step 1f): If `checkPermissions` returned `ask` with a rule-based reason and `ruleBehavior: 'ask'`, respect it even in bypass mode.
7. **Safety checks** (step 1g): Safety-check decisions (e.g., writing to `.git/`, `.claude/`, shell configs) are bypass-immune.
8. **Mode-based decision** (step 2a): Apply the current permission mode -- `bypassPermissions` auto-allows, `dontAsk` converts ask to deny, `auto` routes to the classifier.

### Tool-Specific Validators
Each tool implements a `checkPermissions(input, context)` method that returns a `PermissionResult`. Examples:
- **BashTool**: Splits compound commands, checks each subcommand against allow/deny rules, validates output redirections, checks for sandbox eligibility.
- **FileEditTool / FileWriteTool**: Checks path safety (protected directories), validates against filesystem allow rules.
- **MCP tools**: Checked against `mcp__server__tool` permission rules, with server-level wildcard support.

The tool validator returns `passthrough` when it has no opinion, letting the pipeline continue to mode-based decisions.

### Rule Matching
Rules are matched by `toolMatchesRule()`:
- **Direct match**: rule `toolName` equals the tool's permission-check name.
- **MCP server-level match**: rule `mcp__server1` matches all tools from that server. Wildcard `mcp__server1__*` also works.
- **Content-specific match**: rules like `Bash(prefix:npm install*)` match specific command patterns within a tool.

Rule contents are mapped by `getRuleByContentsForTool()`, enabling efficient lookup of content-specific rules for tools like Bash.

### QueryEngine Wrapper
In the SDK/headless path, `QueryEngine.submitMessage()` wraps `canUseTool` to track denials:
```typescript
if (result.behavior !== 'allow') {
  this.permissionDenials.push({
    tool_name, tool_use_id, tool_input
  })
}
```
These denials are reported back to SDK callers as `SDKPermissionDenial` events.

## Involved Entities
- [Permission System](../entities/permission-system.md) -- rule storage and mode management
- [Tool System](../entities/tool-system.md) -- each tool's `checkPermissions()` implementation
- [Query Engine](../entities/query-engine.md) -- wraps `canUseTool` for denial tracking

## Source Evidence
- `src/hooks/useCanUseTool.tsx` -- `CanUseToolFn` type (line 27), `useCanUseTool` hook (line 28), allow/deny/ask branching (lines 39-170), speculative classifier race (lines 126-159), interactive fallback (lines 160-168)
- `src/utils/permissions/permissions.ts` -- `hasPermissionsToUseTool` (line 473), `hasPermissionsToUseToolInner` (line 1158), deny rule check (line 1171), ask rule check (line 1184), tool `checkPermissions` call (line 1216), safety check immunity (lines 1255-1259), mode-based decision (line 1262+)
- `src/hooks/toolPermission/handlers/interactiveHandler.ts` -- `handleInteractivePermission` for REPL prompts
- `src/hooks/toolPermission/handlers/coordinatorHandler.ts` -- `handleCoordinatorPermission` for automated checks
- `src/hooks/toolPermission/handlers/swarmWorkerHandler.ts` -- `handleSwarmWorkerPermission` for agent hierarchies
- `src/QueryEngine.ts` -- permission denial tracking wrapper (lines 244-271)

## See Also
- [Permission Model](./permission-model.md)
- [Execution Flow](./execution-flow.md)
- [Message Types and Streaming](./message-types-and-streaming.md)
