# Permission and Approval Gating

## Overview

Every tool action that can modify the filesystem, execute a shell command, or make a network request passes through a 3-way permission gate before execution proceeds. The gate evaluates a ruleset of `{permission, pattern, action}` triples against the requested operation and returns one of three outcomes: `allow` (proceed immediately), `deny` (abort with an error), or `ask` (suspend execution and request human approval). The `ask` path publishes a `Permission.Event.Asked` bus event, which the connected client renders as an approval dialog. The user's reply (`"once"`, `"always"`, or `"reject"`) flows back as a `Permission.Reply` and resumes or aborts the waiting tool call.

This model means security policy is declarative (rules in config or session state) and auditable (all requests and replies flow through the bus), while still supporting interactive approval for novel operations.

## Mechanism

### Rule structure

`Permission.Rule` is a zod-validated object with three fields:

```typescript
{
  permission: string   // e.g. "bash", "write", "read"
  pattern:    string   // glob or literal, e.g. "**/*.ts" or "/etc/**"
  action:     "allow" | "deny" | "ask"
}
```

A `Ruleset` is an ordered array of `Rule` objects. Rules are evaluated in declaration order; the first match wins.

### evalRule

`evalRule()` (imported from `./evaluate`) takes a permission name, a set of resource patterns from the incoming request, and the active ruleset. For each rule, it checks:

1. Does the rule's `permission` field match the requested permission name?
2. Does the rule's `pattern` match at least one of the request's patterns using `Wildcard` matching (glob-style with `*` and `**` support)?

`Wildcard` is a utility imported from `@/util/wildcard`. It performs standard glob matching so patterns like `src/**` correctly match `src/foo/bar.ts`.

The first rule that satisfies both conditions determines the outcome. If no rule matches, the default is `ask`.

### Config-level precedence

Rules declared in `opencode.json` (surfaced through `Config`) are prepended to the active ruleset before evaluation. This gives project-level or user-level policy priority over session-level grants. A config rule with `action: "deny"` for a sensitive path cannot be overridden by a session-level `"always"` approval because config rules are evaluated first.

### The ask path and bus event

When `evalRule()` returns `ask`, the permission system constructs a `Permission.Request`:

```typescript
{
  id:         PermissionID     // unique request identifier
  sessionID:  SessionID
  permission: string           // tool name
  patterns:   string[]         // resources the tool wants to access
  metadata:   Record<string, any>
  always:     string[]         // patterns already approved for this session
  tool?:      { messageID, callID }
}
```

This request is published as `Permission.Event.Asked` on the bus. The tool call is then suspended (via an Effect `Deferred`) waiting for the corresponding `Permission.Event.Replied` event.

The connected client receives the `Asked` event through the SSE stream and renders an approval UI. The user selects a reply option.

### Reply processing

`Permission.Reply` is a zod enum: `"once" | "always" | "reject"`.

- `"once"`: The tool call proceeds. No permanent record is written. The approval applies only to this specific invocation.
- `"always"`: The tool call proceeds AND the approved patterns are persisted to `PermissionTable` (a SQLite table keyed by `projectID` and `patterns`). Future tool calls matching the same patterns skip the `ask` path entirely.
- `"reject"`: The waiting `Deferred` is resolved with a `Permission.RejectedError` (tagged `"PermissionRejectedError"`). The tool call aborts and the model receives an error response describing the rejection.

A fourth error class, `Permission.CorrectedError`, carries user feedback text. This is used when the user rejects and provides a correction message, which is surfaced to the model as explanatory context.

### DeniedError

`Permission.DeniedError` is thrown when a matching rule has `action: "deny"`. It carries the active `ruleset` for diagnostic purposes. This is distinct from `RejectedError` (user declined an ask) and `CorrectedError` (user declined with feedback).

### PermissionTable persistence

Approved `"always"` grants are stored in `PermissionTable` indexed by `projectID`. On subsequent requests, the persisted patterns are loaded and included in the `always` array of the `Permission.Request`. `evalRule()` checks these patterns before reaching the `ask` outcome, so previously approved operations are auto-allowed without another interactive prompt.

## Invariants

1. Config-level rules always take precedence over session-level grants. The ruleset is always prepended with config rules before evaluation.
2. A `deny` rule that matches aborts immediately and cannot be overridden by any session-level approval. `DeniedError` is thrown synchronously.
3. `"once"` approvals are not persisted. Restarting the session or re-running the tool will produce another `ask` for the same patterns.
4. `"always"` approvals are scoped to a `projectID`, not globally. Granting access in one project does not affect another project's permission state.
5. Every `Permission.Event.Asked` is matched by exactly one `Permission.Event.Replied` before the waiting tool call resumes or aborts. There is no timeout; the call suspends indefinitely until a reply arrives.
6. `evalRule()` is deterministic given a fixed ruleset. Ordering matters: the first matching rule wins, so more specific rules must precede more general ones in the ruleset array.

## Source Evidence

| File | What it confirms |
| --- | --- |
| `packages/opencode/src/permission/index.ts` | `Permission.Action`, `Permission.Rule`, `Permission.Ruleset`, `Permission.Request`, `Permission.Reply`, `Permission.Event.Asked`, `Permission.Event.Replied`, `RejectedError`, `CorrectedError`, `DeniedError`, `PermissionTable` reference |
| `packages/opencode/src/permission/evaluate.ts` | `evalRule()` implementation with wildcard matching |
| `packages/opencode/src/util/wildcard.ts` | `Wildcard` glob matching utility |
| `packages/opencode/src/session/session.sql.ts` | `PermissionTable` schema (projectID, patterns columns) |
| `packages/opencode/src/config/config.ts` | Config-level rule loading and prepending to session ruleset |
| `packages/opencode/src/bus/bus-event.ts` | `BusEvent.define()` used to type `Permission.Event.Asked` and `Permission.Event.Replied` |

## See Also

- [Tool and Agent Composition](tool-and-agent-composition.md)
- [Client Server Agent Architecture](client-server-agent-architecture.md)
- [Permission System](../entities/permission-system.md)
- [Provider Tool Plugin Interaction Model](../syntheses/provider-tool-plugin-interaction-model.md)
- [Request to Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
