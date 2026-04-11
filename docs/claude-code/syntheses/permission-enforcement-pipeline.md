# Permission Enforcement Pipeline

## Overview

This synthesis describes the full pipeline that determines whether a tool call is allowed, denied, or requires user approval. The pipeline spans from rule loading and parsing at startup, through classification and hook checking at call time, to UI prompting and denial tracking. Every tool call in the system -- whether from the main thread, a subagent, or a forked skill -- passes through this pipeline via the `canUseTool` callback.

## Systems Involved

- [Permission System](../entities/permission-system.md) -- rule loading, classification, decision logic
- [Tool System](../entities/tool-system.md) -- per-tool `checkPermissions()` and `validateInput()`
- [Configuration System](../entities/configuration-system.md) -- settings files that define permission rules
- [State Management](../entities/state-management.md) -- `ToolPermissionContext` on `AppState`

## Interaction Model

### Pipeline Stages

```
Tool call arrives (tool_use block from API)
  |
  v
+---------------------------+
| 1. Input Validation       |
|    tool.validateInput()   |
+------------+--------------+
             |
+------------v--------------+
| 2. Tool-Specific Check    |
|    tool.checkPermissions()|
+------------+--------------+
             |
+------------v--------------+
| 3. Rule Matching          |
|    hasPermissionsToUseTool|
|    - deny rules           |
|    - allow rules          |
|    - ask rules            |
|    - mode-based default   |
+------------+--------------+
             |
      +------+------+
      |      |      |
   allow   deny    ask
      |      |      |
      v      v      v
+-----+  +--+--+ +-+----------------+
|Done |  |Done | | 4. Classifier    |
+-----+  +-----+ |    (feature-gated)|
                  |    - bash        |
                  |    - yolo/auto   |
                  +---+---------+---+
                      |         |
                   allow      ask/deny
                      |         |
                      v         v
                  +---+--+ +---+------------+
                  |Done  | | 5. Hook Check  |
                  +------+ |   PreToolUse   |
                           +---+--------+---+
                               |        |
                            allow    ask/deny
                               |        |
                               v        v
                           +---+--+ +---+-----------+
                           |Done  | | 6. UI Prompt  |
                           +------+ |  (interactive)|
                                    +---+-------+---+
                                        |       |
                                     accept   reject
                                        |       |
                                        v       v
                                    +---+--+ +--+---+
                                    |Allow | |Deny  |
                                    |+save | |+track|
                                    +------+ +------+
```

### Stage 1: Input Validation

Before any permission logic runs, `tool.validateInput()` checks structural correctness of the input. For example, `SkillTool` verifies the skill name exists, and `BashTool` validates the command string. Validation failures return an error to the model without ever reaching the permission system.

### Stage 2: Tool-Specific Permission Check

Each tool implements `checkPermissions(input, context)` which returns a `PermissionResult`:

- `{ behavior: 'allow', updatedInput }` -- tool-specific logic approves (e.g., read-only tools in default mode)
- `{ behavior: 'deny', ... }` -- tool-specific rejection (e.g., `AgentTool` checks for deny rules on the agent type)
- `{ behavior: 'ask', ... }` -- tool defers to the general permission system

Most tools use the `buildTool()` default which returns `allow` and defers to the general system. `BashTool` has the most complex implementation, handling sandbox mode, file path validation, and subcommand decomposition.

### Stage 3: Rule Matching (`hasPermissionsToUseTool`)

The core function in `src/utils/permissions/permissions.ts` evaluates the tool call against three rule sets loaded from the `ToolPermissionContext`:

**Rule sources** (in priority order within each behavior):
- `policySettings` -- enterprise/managed settings
- `globalSettings` -- `~/.claude/settings.json`
- `projectSettings` -- `.claude/settings.json`
- `localProjectSettings` -- `.claude/settings.local.json`
- `cliArg` -- `--allowedTools` flag
- `command` -- skill frontmatter overrides
- `session` -- runtime "always allow for this session" choices

**Rule format**: `"ToolName"` or `"ToolName(pattern)"` where pattern is matched via `tool.preparePermissionMatcher()`. The parser (`permissionRuleParser.ts`) handles escaping of parentheses and backslashes.

**Evaluation order**:
1. **Deny rules** checked first -- if any deny rule matches, the tool is denied immediately.
2. **Allow rules** checked next -- if any allow rule matches, the tool is allowed.
3. **Ask rules** checked next -- if any ask rule matches, the tool requires approval.
4. **Permission mode fallback**: If no rules match, behavior depends on the current mode:
   - `default` mode: write tools ask, read tools allow
   - `plan` mode: all tools ask
   - `bypassPermissions` (YOLO) mode: allow (with classifier gate)

### Stage 4: Classifiers (Feature-Gated)

Two classifier systems can intercept the pipeline when permission mode is `bypassPermissions`:

**Bash Classifier** (`bashClassifier.ts`): Uses an LLM side-query to classify bash commands against prompt-based deny/allow descriptions. Returns `{ matches, confidence, matchedDescription }`. High-confidence matches auto-approve or auto-deny. The result may include a `pendingClassifierCheck` promise that races with the UI prompt.

**YOLO/Auto-Mode Classifier** (`yoloClassifier.ts`): A broader classifier that evaluates any tool call against the conversation transcript. It builds a condensed transcript via `buildTranscriptForClassifier()` and `tool.toAutoClassifierInput()`, then uses an LLM to decide if the action is safe. Can return `allow` or `deny` with a reason. Denial tracking state tracks consecutive and total denials.

### Stage 5: Hook Checking

`PreToolUse` hooks (from `settings.json` hook configuration) run before the tool executes. Hooks can:
- Return `{ decision: "allow" }` to approve
- Return `{ decision: "deny", reason }` to reject
- Return `{ decision: "ask", reason }` to force a user prompt
- Modify the input via `updatedInput`

Hook matching uses the tool name and optional pattern (via `tool.preparePermissionMatcher()`).

### Stage 6: UI Prompting

When the decision is `ask`, the pipeline reaches the user interface:

**Interactive mode** (`handleInteractivePermission`): Adds the request to the `toolUseConfirmQueue`. The React permission prompt UI displays the tool name, description, input, and decision reason. The user can:
- Accept once
- Accept and add an "always allow" rule (to session, project, or global settings)
- Reject once
- Reject and add an "always deny" rule

**Non-interactive mode**: Auto-rejects with `AUTO_REJECT_MESSAGE`.

**Swarm worker mode** (`handleSwarmWorkerPermission`): Delegates permission to the coordinator.

**Channel permissions** (`channelPermissions.ts`): When enabled, permission prompts are also relayed to external channels (Telegram, Discord, etc.) and the first response wins via a race.

### Denial Tracking

`denialTracking.ts` maintains a `DenialTrackingState`:

```typescript
type DenialTrackingState = {
  consecutiveDenials: number  // reset on success
  totalDenials: number        // monotonically increasing
}
```

When `consecutiveDenials >= 3` or `totalDenials >= 20`, the classifier falls back to prompting (`shouldFallbackToPrompting()`). This prevents the classifier from repeatedly denying legitimate actions.

Denial state lives on `AppState` for the main thread, or on `ToolUseContext.localDenialTracking` for async subagents whose `setAppState` is a no-op.

### Rule Persistence

When a user makes an "always allow/deny" choice at the UI prompt, the rule is persisted via `applyPermissionUpdate()` which writes to the appropriate settings file. Rules are reloaded from settings on each permission check via `ToolPermissionContext` on `AppState`.

## Key Interfaces

### PermissionResult (`src/utils/permissions/PermissionResult.ts`)

```typescript
type PermissionResult =
  | { behavior: 'allow'; updatedInput?: Record<string, unknown>; decisionReason?: PermissionDecisionReason }
  | { behavior: 'deny'; decisionReason?: PermissionDecisionReason }
  | { behavior: 'ask'; pendingClassifierCheck?: Promise<ClassifierResult>; updatedInput?: unknown; suggestions?: unknown; decisionReason?: PermissionDecisionReason }
```

### CanUseToolFn (`src/hooks/useCanUseTool.tsx`)

```typescript
type CanUseToolFn<Input> = (
  tool: Tool,
  input: Input,
  toolUseContext: ToolUseContext,
  assistantMessage: AssistantMessage,
  toolUseID: string,
  forceDecision?: PermissionDecision<Input>,
) => Promise<PermissionDecision<Input>>
```

### ToolPermissionContext (`src/Tool.ts`)

```typescript
type ToolPermissionContext = DeepImmutable<{
  mode: PermissionMode                    // 'default' | 'plan' | 'bypassPermissions'
  additionalWorkingDirectories: Map<string, AdditionalWorkingDirectory>
  alwaysAllowRules: ToolPermissionRulesBySource
  alwaysDenyRules: ToolPermissionRulesBySource
  alwaysAskRules: ToolPermissionRulesBySource
  isBypassPermissionsModeAvailable: boolean
  shouldAvoidPermissionPrompts?: boolean  // background agents
  awaitAutomatedChecksBeforeDialog?: boolean  // coordinator workers
}>
```

### DenialTrackingState (`src/utils/permissions/denialTracking.ts`)

```typescript
type DenialTrackingState = { consecutiveDenials: number; totalDenials: number }
const DENIAL_LIMITS = { maxConsecutive: 3, maxTotal: 20 }
function shouldFallbackToPrompting(state: DenialTrackingState): boolean
```

### PermissionRuleValue (`src/utils/permissions/permissionRuleParser.ts`)

```typescript
// Parsed from strings like "Bash(git *)" or "FileEdit"
type PermissionRuleValue = {
  toolName: string
  ruleContent?: string  // the pattern inside parentheses, if any
}
```

## See Also

- [Permission System](../entities/permission-system.md) -- detailed entity documentation
- [Tool System](../entities/tool-system.md) -- `checkPermissions()` on individual tools
- [Configuration System](../entities/configuration-system.md) -- settings files and rule sources
- [State Management](../entities/state-management.md) -- `ToolPermissionContext` on `AppState`
- [Query Loop Orchestration](./query-loop-orchestration.md) -- where `canUseTool` is called in the loop
- [Agent-Tool-Skill Triad](./agent-tool-skill-triad.md) -- how subagents inherit and narrow permissions
- [MCP Integration Architecture](./mcp-integration-architecture.md) -- channel permissions for MCP servers
