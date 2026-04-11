# Permission System

## Overview

The permission system is a layered framework that gates every tool execution in Claude Code. Before any tool call reaches its implementation, the system evaluates a cascade of deny rules, allow rules, tool-specific permission checks, mode-based policies, hooks, AI classifiers, and user prompts to produce one of three outcomes: **allow**, **deny**, or **ask** (prompt the user). A fourth internal value, **passthrough**, lets a tool delegate the decision to the outer framework.

The system is designed so that higher-priority deny signals are always respected (even in bypass mode for safety-critical paths), while less restrictive modes progressively reduce the number of user prompts through classifiers and fast-path heuristics.

## Key Types

### PermissionMode

Defined in `types/permissions.ts` as a union of `ExternalPermissionMode` (user-addressable) and internal-only modes:

| Mode | External | Description |
|------|----------|-------------|
| `default` | Yes | Baseline mode; prompts on write operations and bash commands |
| `acceptEdits` | Yes | Deprecated; auto-allows file edits inside the working directory |
| `bypassPermissions` | Yes | Auto-allows all tool calls except safety-check paths and explicit ask rules |
| `dontAsk` | Yes | Converts every `ask` result into `deny` -- never prompts the user |
| `plan` | Yes | Temporary mode during plan generation; inherits bypass if the user started in bypassPermissions |
| `auto` | No (internal) | Classifier-driven; uses YOLO/bash classifiers to decide without prompting. Gated behind the `TRANSCRIPT_CLASSIFIER` feature flag |
| `bubble` | No (internal) | Prompts in the parent agent, auto-allows in subagents |

The runtime validation set `INTERNAL_PERMISSION_MODES` conditionally includes `auto` when the transcript classifier feature is enabled. `bubble` is never user-addressable and is excluded from both external and internal mode lists.

### PermissionBehavior / PermissionResult

`PermissionBehavior` is the core three-value enum:

```typescript
type PermissionBehavior = 'allow' | 'deny' | 'ask'
```

`PermissionResult` extends this with a fourth value, `passthrough`, which signals that a tool's `checkPermissions()` has no opinion and the outer framework should decide:

```typescript
type PermissionResult<Input> =
  | PermissionDecision<Input>          // allow | ask | deny
  | { behavior: 'passthrough'; ... }   // delegate to framework
```

Each decision variant carries specific metadata:

- **PermissionAllowDecision** -- may include `updatedInput` (modified tool input), `acceptFeedback`, and `contentBlocks`.
- **PermissionAskDecision** -- includes a human-readable `message`, optional `suggestions` (PermissionUpdate proposals for "always allow"), optional `pendingClassifierCheck` for async auto-approval, and optional `blockedPath`.
- **PermissionDenyDecision** -- includes `message` and a mandatory `decisionReason`.

### PermissionDecisionReason

A discriminated union that records *why* a decision was made. The `type` field identifies the source:

| Type | Meaning |
|------|---------|
| `rule` | A permission rule from settings matched |
| `mode` | The current PermissionMode dictated the outcome |
| `hook` | A PreToolUse or PermissionRequest hook overrode the decision |
| `classifier` | The YOLO or bash classifier blocked/allowed the action |
| `safetyCheck` | A safety check flagged the path (e.g., `.git/`, `.claude/`, shell configs). Has a `classifierApprovable` boolean -- when false, the path is immune to bypass and auto modes |
| `sandboxOverride` | The action runs outside the sandbox (`excludedCommand` or `dangerouslyDisableSandbox`) |
| `subcommandResults` | A compound bash command where individual subcommands had different results |
| `permissionPromptTool` | A permission prompt tool (e.g., MCP-based) made the decision |
| `asyncAgent` | An async/headless agent context denied because no interactive prompt is available |
| `workingDir` | The action targets a path outside allowed working directories |
| `other` | Catch-all for miscellaneous reasons |

### ToolPermissionRulesBySource

Maps each `PermissionRuleSource` to an array of rule strings:

```typescript
type ToolPermissionRulesBySource = {
  [T in PermissionRuleSource]?: string[]
}
```

The `ToolPermissionContext` carries three such maps: `alwaysAllowRules`, `alwaysDenyRules`, and `alwaysAskRules`, plus the current `mode`, `additionalWorkingDirectories`, and flags like `isBypassPermissionsModeAvailable` and `shouldAvoidPermissionPrompts`.

### PermissionRule

A rule binding a source, a behavior, and a value:

```typescript
type PermissionRule = {
  source: PermissionRuleSource
  ruleBehavior: PermissionBehavior   // allow | deny | ask
  ruleValue: PermissionRuleValue     // { toolName, ruleContent? }
}
```

Rule values use the string format `ToolName` or `ToolName(content)`, where content can contain escaped parentheses. The parser in `permissionRuleParser.ts` handles legacy tool name aliases (e.g., `Task` maps to `AgentTool`) and wildcard matching for MCP servers (e.g., `mcp__server1` matches all tools from that server).

## Permission Modes

### default

The baseline mode. All write operations and bash commands trigger a user prompt. Read-only tools (FileRead, Grep, Glob, LSP, etc.) proceed without prompting. This is the mode every new session starts in unless overridden by settings or CLI flags.

### auto

Available only when the `TRANSCRIPT_CLASSIFIER` feature flag is enabled. Instead of prompting, the system runs an AI classifier (the "YOLO classifier") against the current transcript and proposed tool call. The classifier returns `shouldBlock: boolean` with a confidence level and reason.

Before invoking the classifier, auto mode applies two fast paths to avoid expensive API calls:
1. **acceptEdits fast path** -- re-evaluates the tool's `checkPermissions()` as if in acceptEdits mode. If the action would be allowed (e.g., a file edit inside the working directory), it is auto-allowed without a classifier call.
2. **Safe-tool allowlist** -- a hardcoded set of read-only and metadata-only tools (`SAFE_YOLO_ALLOWLISTED_TOOLS`) that never need classification. Includes FileRead, Grep, Glob, TodoWrite, task management tools, plan mode tools, and more.

If the classifier is unavailable (API error, transcript too long), the system falls back to prompting or denying depending on the `classifierFailClosedEnabled` flag. Denial tracking (see below) can also force a fallback.

### bubble

An internal mode for subagent permission delegation. When a parent agent spawns a subagent, the subagent runs in bubble mode: it auto-allows tool calls that would otherwise prompt, while the parent handles any interactive approval. Not user-addressable.

### bypassPermissions

Auto-allows all tool calls with two exceptions:
1. **Content-specific ask rules** -- if a user explicitly configured an ask rule with content (e.g., `Bash(npm publish:*)`), it is respected even in bypass mode.
2. **Safety-check paths** -- paths flagged by `checkPathSafetyForAutoEdit` (`.git/`, `.claude/`, `.vscode/`, shell config files) always prompt regardless of mode.

When the user is in plan mode but originally started in bypassPermissions, the system inherits the bypass behavior.

### plan

A temporary mode activated during plan generation. If the user originally started with bypassPermissions, plan mode inherits full bypass behavior. Otherwise, it behaves like default mode with an additional flag for plan-specific logic.

### dontAsk

Converts every `ask` decision into `deny` at the end of the permission pipeline. The tool receives a rejection message (`DONT_ASK_REJECT_MESSAGE`) and the model must find an alternative approach. Useful for fully non-interactive contexts.

### acceptEdits (deprecated)

Legacy mode that auto-allows file edits inside the current working directory while still prompting for bash commands and edits outside the working directory. Superseded by auto mode but retained for backward compatibility and used as a fast-path heuristic in auto mode.

## Decision Flow

The main entry point is `hasPermissionsToUseTool()`, which wraps `hasPermissionsToUseToolInner()` with post-processing for mode-specific transformations and denial tracking.

### Step 1: Deny and Ask Rule Evaluation

1. **1a -- Tool-level deny rules**: Check if the entire tool is denied via `getDenyRuleForTool()`. If matched, return `deny` immediately.
2. **1b -- Tool-level ask rules**: Check if the entire tool has an ask rule via `getAskRuleForTool()`. If matched, return `ask` (unless sandboxed bash auto-allow applies).
3. **1c -- Tool-specific checkPermissions()**: Call the tool's own `checkPermissions(parsedInput, context)` method, which returns `allow`, `deny`, `ask`, or `passthrough`. Each tool implements its own content-aware logic (e.g., BashTool checks command prefixes against allow/deny rules, FileWriteTool checks path safety).
4. **1d -- Tool denied**: If the tool's checkPermissions returned `deny`, respect it.
5. **1e -- Requires user interaction**: If the tool declares `requiresUserInteraction()` and returned `ask`, respect it even in bypass mode.
6. **1f -- Content-specific ask rules**: If checkPermissions returned `ask` with a rule-based reason where `ruleBehavior === 'ask'`, respect it even in bypass mode.
7. **1g -- Safety checks**: If checkPermissions returned `ask` with a `safetyCheck` reason, respect it (bypass-immune).

### Step 2: Mode-Based Decisions

1. **2a -- Bypass check**: If the mode is `bypassPermissions` (or `plan` with bypass available), return `allow`.
2. **2b -- Tool-level allow rules**: If the entire tool is in the always-allow list, return `allow`.

### Step 3: Passthrough Conversion

Convert any remaining `passthrough` result to `ask` with an appropriate message.

### Post-Processing (in the outer function)

After `hasPermissionsToUseToolInner` returns:

- **On allow**: Reset consecutive denial counter if in auto mode.
- **On ask with dontAsk mode**: Convert to `deny`.
- **On ask with auto mode**: Run the classifier pipeline:
  1. Check safety-check immunity (non-classifierApprovable safetyChecks stay as `ask`).
  2. Check if user interaction is required.
  3. Try the acceptEdits fast path.
  4. Check the safe-tool allowlist.
  5. Run the YOLO classifier (`classifyYoloAction`).
  6. If the classifier says `shouldBlock`, record a denial and either prompt the user or auto-deny (headless agents).
  7. If the classifier says allow, record success and return `allow`.
  8. If the classifier is unavailable, fall back based on `classifierFailClosedEnabled`.

### Denial Tracking

The `denialTracking` module tracks consecutive and total classifier denials per session:

- **Max consecutive denials**: 3 (after 3 consecutive blocked actions, fall back to interactive prompting)
- **Max total denials**: 20 (after 20 total blocked actions in the session, fall back permanently)
- On any successful tool use, the consecutive counter resets to 0.

This prevents the classifier from permanently blocking a legitimate workflow.

### PreToolUse Hooks

Before the permission prompt is shown to the user (or instead of it), the `executePermissionRequestHooks` function runs any configured `PermissionRequest` hooks. These hooks can:
- **Allow** the action (with optional updated input and permission rule updates)
- **Deny** the action (with optional interrupt to abort the entire agent)
- **Pass** (no decision, continue to normal prompting)

Headless/async agents always try hooks before falling back to auto-deny, giving hook-based automation a chance to handle permissions in non-interactive contexts.

## Rule Sources

Permission rules come from eight sources, evaluated in a defined priority order. The `PERMISSION_RULE_SOURCES` constant combines setting sources with runtime sources:

| Priority | Source | Description |
|----------|--------|-------------|
| 1 | `policySettings` | Managed/enterprise policy settings; when `allowManagedPermissionRulesOnly` is set, only these rules are respected |
| 2 | `flagSettings` | Feature flag-derived settings |
| 3 | `userSettings` | User-level `~/.claude/settings.json` |
| 4 | `projectSettings` | Project-level `.claude/settings.json` |
| 5 | `localSettings` | Local (gitignored) `.claude/settings.local.json` |
| 6 | `cliArg` | Rules passed via CLI flags (e.g., `--allowedTools`) |
| 7 | `command` | Rules injected by slash commands during a session |
| 8 | `session` | Rules added interactively during the current session (e.g., "always allow" responses to permission prompts) |

Rules are aggregated into `ToolPermissionContext.alwaysAllowRules`, `alwaysDenyRules`, and `alwaysAskRules`, each keyed by source. When checking, deny rules are evaluated first, then ask rules, then allow rules. The `permissionsLoader.ts` module handles reading rules from each settings file and merging them into the context.

### Rule Format

Rules follow the string format `ToolName` or `ToolName(content)`:

- `Bash` -- matches the entire Bash tool
- `Bash(npm install)` -- matches only bash commands matching the "npm install" prefix/pattern
- `mcp__server1` -- matches all tools from MCP server "server1"
- `mcp__server1__*` -- wildcard matching all tools from a server

Parentheses in content are escaped with backslashes: `Bash(python -c "print\(1\)")`.

## Source Files

| File | Description |
|------|-------------|
| `src/types/permissions.ts` | All pure type definitions (PermissionMode, PermissionResult, PermissionDecision, PermissionDecisionReason, PermissionRule, ClassifierResult, etc.) |
| `src/utils/permissions/permissions.ts` | Core permission engine: `hasPermissionsToUseTool`, rule matching, deny/allow/ask rule getters, classifier integration, denial tracking integration |
| `src/utils/permissions/PermissionMode.ts` | Mode configuration (titles, symbols, colors), mode validation schemas, `permissionModeFromString` |
| `src/utils/permissions/PermissionResult.ts` | Re-exports result types, `getRuleBehaviorDescription` helper |
| `src/utils/permissions/PermissionRule.ts` | Re-exports rule types, `permissionBehaviorSchema` and `permissionRuleValueSchema` Zod schemas |
| `src/utils/permissions/permissionRuleParser.ts` | `permissionRuleValueFromString` / `permissionRuleValueToString` with escape handling, legacy tool name normalization |
| `src/utils/permissions/permissionsLoader.ts` | Loads rules from all setting sources, manages `allowManagedPermissionRulesOnly` policy, settings file I/O |
| `src/utils/permissions/PermissionUpdate.ts` | `applyPermissionUpdate` / `applyPermissionUpdates` / `persistPermissionUpdates` for modifying permission state |
| `src/utils/permissions/classifierDecision.ts` | Auto-mode tool allowlist (`SAFE_YOLO_ALLOWLISTED_TOOLS`), `isAutoModeAllowlistedTool` |
| `src/utils/permissions/yoloClassifier.ts` | YOLO transcript classifier: `classifyYoloAction`, `formatActionForClassifier`, prompt construction |
| `src/utils/permissions/bashClassifier.ts` | Bash-specific classifier with allow/deny description lists |
| `src/utils/permissions/denialTracking.ts` | Consecutive and total denial counters, `shouldFallbackToPrompting` threshold logic |
| `src/utils/permissions/getNextPermissionMode.ts` | Mode cycling logic for Shift+Tab (default -> acceptEdits -> plan -> bypass -> auto -> default) |
| `src/utils/permissions/permissionSetup.ts` | Mode gate checks, `transitionPermissionMode`, auto-mode availability verification |
| `src/utils/permissions/permissionExplainer.ts` | Risk-level assessment and human-readable explanations for permission decisions |
| `src/utils/permissions/pathValidation.ts` | Working directory and path safety validation |
| `src/utils/permissions/dangerousPatterns.ts` | Detection of dangerous permission rule patterns |
| `src/utils/permissions/shadowedRuleDetection.ts` | Detection of rules that are shadowed (overridden) by higher-priority rules |
| `src/utils/permissions/shellRuleMatching.ts` | Shell command pattern matching for bash permission rules |
| `src/utils/permissions/bypassPermissionsKillswitch.ts` | Emergency killswitch for bypass mode |

## See Also

- [Tool System](tool-system.md)
- [Permission Model](../concepts/permission-model.md)
- [Tool Permission Gating](../concepts/tool-permission-gating.md)
- [Permission Enforcement Pipeline](../syntheses/permission-enforcement-pipeline.md)
