# Permission Model

## Overview
The Permission Model is the layered allow/deny/ask system that governs every tool invocation in Claude Code. It exists to balance safety (preventing destructive or unauthorized actions) with usability (avoiding excessive prompting). The model is designed so that multiple sources of permission rules -- user settings, project settings, CLI arguments, policy settings, and session state -- compose predictably through a priority pipeline.

## Mechanism

### Permission Modes
Claude Code supports several permission modes, each defining a baseline posture for how tool calls are handled:

| Mode | Behavior |
|------|----------|
| `default` | Prompt the user for any tool call not covered by an explicit allow rule |
| `acceptEdits` | Auto-allow file edits; prompt for other sensitive operations |
| `bypassPermissions` | Auto-allow all tool calls (except safety-check-immune paths) |
| `dontAsk` | Never prompt; deny anything that would normally require asking |
| `plan` | Read-only planning mode; denies write operations |
| `auto` | Use an AI classifier to decide allow/deny instead of prompting (feature-gated behind `TRANSCRIPT_CLASSIFIER`) |
| `bubble` | Internal mode for propagating permission decisions upward in agent hierarchies |

Modes are defined in `types/permissions.ts` as the `PermissionMode` union type. The runtime-addressable set (`INTERNAL_PERMISSION_MODES`) conditionally includes `auto` when the transcript classifier feature is enabled.

### Permission Behaviors
Every permission decision resolves to one of three behaviors:

- **`allow`** -- the tool call proceeds. May include `updatedInput` (modified arguments) and `decisionReason` for auditing.
- **`deny`** -- the tool call is rejected. Includes a `message` explaining why and a `decisionReason`.
- **`ask`** -- the user (or an automated classifier) must decide. Includes a `message`, optional `suggestions` for permission updates, and optionally a `pendingClassifierCheck` for async auto-mode evaluation.

A fourth internal behavior, **`passthrough`**, signals that no rule matched and the pipeline should continue to the next stage.

### Layered Rule System
Permission rules originate from multiple sources, defined by `PermissionRuleSource`:

1. **`policySettings`** -- Enterprise/organizational policies (highest priority)
2. **`flagSettings`** -- Feature flag overrides
3. **`userSettings`** -- User's `~/.claude/settings.json`
4. **`projectSettings`** -- Project-level `.claude/settings.json`
5. **`localSettings`** -- Local (gitignored) project settings
6. **`cliArg`** -- `--allowedTools` / `--disallowedTools` CLI flags
7. **`command`** -- Slash command overrides
8. **`session`** -- Runtime grants within the current session

Each rule specifies a `PermissionRuleValue` (tool name + optional content pattern) and a `PermissionBehavior`. Rules are stored in `ToolPermissionContext` as three maps: `alwaysAllowRules`, `alwaysDenyRules`, and `alwaysAskRules`, each keyed by source.

### Classifier Pipeline (Auto Mode)
When the permission mode is `auto`, tool calls that would normally trigger an `ask` are routed to a two-stage AI classifier (`yoloClassifier.ts`):
1. **Fast stage**: A lightweight check against known-safe patterns.
2. **Thinking stage**: A deeper analysis using the conversation transcript as context.

The classifier returns a `YoloClassifierResult` with `shouldBlock`, a `reason`, confidence metadata, token usage, and timing. If the classifier is unavailable (API error, transcript too long), the system falls back to user prompting.

### Decision Reasons
Every permission decision carries a `PermissionDecisionReason` explaining its provenance:
- `rule` -- matched an explicit allow/deny/ask rule
- `mode` -- the current permission mode dictated the outcome
- `classifier` -- an AI classifier made the decision
- `hook` -- a pre-execution hook intervened
- `safetyCheck` -- a safety invariant (e.g., writing to `.git/`) triggered
- `sandboxOverride` -- sandbox mode overrode the default behavior
- `workingDir` -- the operation targeted a path outside allowed directories
- `subcommandResults` -- compound bash commands with per-subcommand results
- `permissionPromptTool` -- an external permission prompt tool decided
- `asyncAgent` -- an async agent worker decided
- `other` -- catch-all

### Denial Tracking UX
To prevent the model from endlessly retrying denied actions, Claude Code implements denial tracking (`denialTracking.ts`):
- Consecutive denials for the same tool are counted.
- After exceeding `DENIAL_LIMITS`, the system falls back to explicit user prompting even in auto mode (`shouldFallbackToPrompting`).
- A successful tool use (`recordSuccess`) resets the consecutive denial counter.
- In auto mode, denied actions trigger an inline notification: "tool_name denied by auto mode" with a hint to run `/permissions`.

### Permission Updates
Users can modify permission rules at runtime. `PermissionUpdate` supports operations:
- `addRules` / `replaceRules` / `removeRules` -- manage allow/deny/ask rules
- `setMode` -- change the active permission mode
- `addDirectories` / `removeDirectories` -- manage additional working directories

Updates are persisted to the appropriate destination (`userSettings`, `projectSettings`, `localSettings`, `session`, `cliArg`) via `persistPermissionUpdates()`.

## Involved Entities
- [Permission System](../entities/permission-system.md) -- the runtime implementation
- [Tool System](../entities/tool-system.md) -- each tool's `checkPermissions()` method
- [Tool Permission Gating](./tool-permission-gating.md) -- per-call permission checking hook

## Source Evidence
- `src/types/permissions.ts` -- all type definitions: `PermissionMode`, `PermissionBehavior`, `PermissionRule`, `PermissionDecision`, `PermissionResult`, `PermissionDecisionReason`, `YoloClassifierResult`, `ToolPermissionContext` (full file)
- `src/utils/permissions/permissions.ts` -- `hasPermissionsToUseTool` (line 473), `hasPermissionsToUseToolInner` (line 1158), rule matching (`getAllowRules`/`getDenyRules`/`getAskRules`), `toolMatchesRule` (line 238), denial tracking integration (lines 483-500)
- `src/utils/permissions/denialTracking.ts` -- `createDenialTrackingState`, `recordDenial`, `recordSuccess`, `shouldFallbackToPrompting`, `DENIAL_LIMITS`
- `src/utils/permissions/yoloClassifier.ts` -- `classifyYoloAction`, `formatActionForClassifier`
- `src/utils/permissions/PermissionMode.ts` -- `permissionModeTitle`, `PERMISSION_MODES`

## See Also
- [Tool Permission Gating](./tool-permission-gating.md)
- [Execution Flow](./execution-flow.md)
- [Message Types and Streaming](./message-types-and-streaming.md)
