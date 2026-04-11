# Concept: The Permission System

**Type:** Concept

---

## Overview

The permission system is the cross-cutting security and authorization layer that governs every tool invocation in Claude Code. No tool executes without passing through a permission check. The system provides a uniform interface across all tools while supporting tool-specific rule vocabularies — wildcard shell patterns for BashTool, hostname-based rules for WebFetchTool, path-based rules for file tools, agent-name rules for AgentTool.

---

## Core Abstraction

Every `ToolDef` must implement:

```ts
checkPermissions(input: Input, context: ToolPermissionContext): Promise<PermissionResult>
```

`PermissionResult` is a discriminated union:

```ts
type PermissionResult =
  | { behavior: 'allow' }
  | { behavior: 'ask';  message: string }
  | { behavior: 'deny'; message: string }
  | { behavior: 'passthrough'; message: string }
```

- **allow** — proceed immediately, no user prompt
- **ask** — pause and display `message` to the user; resume only if confirmed
- **deny** — block the action, display `message`, do not execute
- **passthrough** — defer to the next rule or default behavior

---

## Permission Rules

Rules are stored as a list of `PermissionRule` objects. Each rule has:
- A `tool` selector (which tool it applies to)
- A `behavior` (`allow` | `ask` | `deny`)
- A `value` — tool-specific content (e.g., `Bash(git:*)` or `WebFetch(domain:github.com)`)

Rules are evaluated in order; the first matching rule wins.

### BashTool Rules

`bashPermissions.ts` evaluates rules against the parsed command:

- `Bash(git:*)` — allow all git subcommands
- `Bash(npm:install)` — allow only `npm install`
- `Bash(rm:*)` — deny all rm commands

`permissionRuleExtractPrefix()` extracts the base command from the rule value. `matchWildcardPattern()` does glob-style matching against the actual command prefix.

When no explicit rule matches, the system falls back to the **LLM bash classifier** (`utils/permissions/bashClassifier.ts`) which uses a smaller model to classify whether a command is safe to auto-allow or should require user confirmation.

### FileSystem Rules

`utils/permissions/filesystem.ts` provides:

- `checkReadPermissionForTool()` — validates against path-based read allow lists
- `checkWritePermissionForTool()` — validates against path-based write allow lists
- `getFileReadIgnorePatterns()` — patterns for files that should never be read

### WebFetch Rules

WebFetchTool extracts the hostname from the URL and formats the rule content as `domain:<hostname>`. `getRuleByContentsForTool()` finds the matching configured rule.

`preapproved.ts` contains a list of pre-approved hostnames that never require user confirmation (e.g., `api.anthropic.com`).

### Agent Rules

AgentTool uses `getDenyRuleForAgent()` and `filterDeniedAgents()` to evaluate rules based on agent name or type. This allows administrators to prevent certain agent types from being spawned.

---

## Permission Modes

The session can operate in different permission modes (defined in `utils/permissions/PermissionMode.ts`):

| Mode | Behavior |
|------|----------|
| `default` | Standard ask/allow/deny evaluation |
| `plan` | All destructive actions require explicit plan approval |
| `readonly` | Only read actions permitted; writes blocked |
| `bypassPermissions` | All permission checks auto-approved (used in testing) |
| `acceptEdits` | File edits auto-approved without prompting |

---

## Classifier-Based Permissions

When explicit rules are insufficient, the system uses an LLM classifier (`bashClassifier.ts`):

```ts
function classifyBashCommand(command: string): Promise<ClassifierResult>
```

The classifier returns `allow`, `ask`, or `deny` based on the semantic content of the command. This is a defense-in-depth mechanism for commands that don't match any explicit rule.

`isClassifierPermissionsEnabled()` gates this feature via a GrowthBook flag.

---

## User Interaction

When `behavior === 'ask'`, the tool call is paused and `createPermissionRequestMessage()` generates a structured message displayed to the user. The user's response is captured and fed back into the permission evaluation loop. If the user confirms, the tool proceeds; if they deny, the tool returns an error result.

---

## Relationship to Tools

| Tool | Primary Permission Mechanism |
|------|------------------------------|
| BashTool | Wildcard rule matching + AST security + LLM classifier |
| FileEditTool | Path-based write permission rules |
| FileReadTool | Path-based read permission rules + ignore patterns |
| WebFetchTool | Hostname-based rules + preapproved list |
| AgentTool | Agent name/type deny rules |
| MCPTool | Always returns `passthrough` — overridden by mcpClient |

---

## Cross-References

- [overview.md](overview.md) — system context
- [entity_bashtool.md](entity_bashtool.md) — most complex permission implementation
- [entity_agenttool.md](entity_agenttool.md) — agent-level permission control
- [synthesis_composition.md](synthesis_composition.md) — how permissions propagate across agent boundaries
- [index.md](index.md) — wiki navigation
