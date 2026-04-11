# Permission System

## Overview

The permission system is the gatekeeper for every tool call that an AI agent wants to execute. Before a tool runs, it must pass through the permission layer, which evaluates the requested operation against a priority-ordered ruleset, decides whether to allow, deny, or pause and ask the user, then persists any "always approve" answers so the user is not repeatedly interrupted for the same pattern.

Permissions are first-class runtime contracts, not cosmetic prompts. A `deny` decision raises a typed error that halts the tool call and surfaces a policy message back to the model. An `ask` decision blocks execution in an Effect `Deferred` until the user replies via the HTTP API, and a `reject` reply cascades to cancel every other pending request from the same session.

The system lives in `src/permission/` and integrates tightly with the session bus, the project database, and the `InstanceState` scoping mechanism that ties per-project state to the current async context.

---

## Key Types

### `Permission.Action`

```ts
// "allow" | "deny" | "ask"
export const Action = z.enum(["allow", "deny", "ask"]).meta({ ref: "PermissionAction" })
export type Action = z.infer<typeof Action>
```

- `"allow"` — the tool call proceeds immediately.
- `"deny"` — the call is rejected and a `DeniedError` is raised with the matching rules attached.
- `"ask"` — execution is suspended until the user replies.

---

### `Permission.Rule`

```ts
export const Rule = z.object({
  permission: z.string(),   // glob pattern for the permission name, e.g. "bash" or "file.*"
  pattern:    z.string(),   // glob pattern for the specific resource, e.g. "/tmp/**"
  action:     Action,
}).meta({ ref: "PermissionRule" })
```

Rules are matched via `Wildcard.match()` on both `permission` and `pattern`, so wildcards in both dimensions are supported.

---

### `Permission.Ruleset`

```ts
export const Ruleset = Rule.array().meta({ ref: "PermissionRuleset" })
export type Ruleset = z.infer<typeof Ruleset>
```

An ordered array of `Rule`. Evaluation uses `findLast`, so later rules win over earlier ones. The config-level ruleset is provided by the caller; the session-level `approved` list is accumulated in memory during a session and also persisted to `PermissionTable`.

---

### `Permission.Request`

```ts
export const Request = z.object({
  id:         PermissionID.zod,         // unique ascending ID for this pending request
  sessionID:  SessionID.zod,            // which session is requesting
  permission: z.string(),               // the permission name being requested (e.g. "bash")
  patterns:   z.string().array(),       // resource patterns being accessed (e.g. ["/etc/hosts"])
  metadata:   z.record(z.string(), z.any()), // arbitrary tool metadata for display
  always:     z.string().array(),       // patterns the tool suggests could be "always allowed"
  tool:       z.object({
    messageID: MessageID.zod,
    callID:    z.string(),
  }).optional(),
}).meta({ ref: "PermissionRequest" })
```

`always` is an advisory list from the tool; when the user replies `"always"`, these patterns are appended to the in-memory `approved` ruleset and written to the database.

---

### `Permission.Reply`

```ts
export const Reply = z.enum(["once", "always", "reject"])
export type Reply = z.infer<typeof Reply>
```

- `"once"` — approve this single request, do not persist.
- `"always"` — approve and persist; future requests matching the same patterns are auto-allowed.
- `"reject"` — deny this request and cancel all other pending requests from the same session.

---

### `Permission.Approval`

```ts
export const Approval = z.object({
  projectID: ProjectID.zod,
  patterns:  z.string().array(),
})
```

Used when writing project-level approvals to the database.

---

### `Permission.Event.Asked` and `Permission.Event.Replied`

```ts
export const Event = {
  Asked: BusEvent.define("permission.asked", Request),
  Replied: BusEvent.define(
    "permission.replied",
    z.object({
      sessionID: SessionID.zod,
      requestID: PermissionID.zod,
      reply:     Reply,
    }),
  ),
}
```

Both events are published on the instance `Bus`. Clients subscribe to `permission.asked` over SSE to show the user a prompt, and the API route calls `Permission.Service.reply()` to complete the deferred.

---

### Error Types

| Class | Tagged error name | When raised |
|---|---|---|
| `DeniedError` | `PermissionDeniedError` | A `deny` rule matched; carries the relevant ruleset for model feedback |
| `RejectedError` | `PermissionRejectedError` | User replied `"reject"` |
| `CorrectedError` | `PermissionCorrectedError` | User rejected with a feedback message; carries `feedback: string` |

---

### `PermissionTable` (DB)

Defined in `src/session/session.sql.ts`. Stores project-level approved rules as a JSON array, keyed by `project_id`. On instance boot the row is loaded into the in-memory `approved: Ruleset` state, and it is written back whenever the user replies `"always"`.

---

## Architecture

```
src/permission/
  index.ts       ← public namespace; Service layer, ask/reply/list, bus integration
  evaluate.ts    ← pure function: evalRule(permission, pattern, ...rulesets)
  schema.ts      ← PermissionID branded type (ascending IDs)

src/session/
  session.sql.ts ← PermissionTable: persists project-level approved rules

src/util/
  wildcard.ts    ← Wildcard.match() for glob matching on permission and pattern fields
```

`index.ts` imports `evaluate` from `evaluate.ts` and `Wildcard` from `util/wildcard`. The `Permission.Service` Effect layer holds all mutable state in an `InstanceState`-scoped slot so that each project instance has its own independent pending map and approved list.

The `AskInput` type extends `Request.partial({ id: true })` and adds a `ruleset` field so callers can pass the config-level rules alongside the request. The service merges `ruleset` and `approved` for evaluation but does not expose `approved` publicly.

---

## Runtime Behavior

1. **Tool calls `Permission.Service.ask()`** with `AskInput` — includes the permission name, resource patterns, config ruleset, and optional `always` hints.

2. **Each pattern is evaluated independently.** `evalRule(permission, pattern, configRuleset, approvedRuleset)` is called. The function flattens both arrays and calls `rules.findLast(r => Wildcard.match(permission, r.permission) && Wildcard.match(pattern, r.pattern))`. If no rule matches, the default is `{ action: "ask" }`.

3. **If any pattern yields `"deny"`**, `ask()` immediately raises `DeniedError` with the matching config rules attached. Execution stops.

4. **If all patterns yield `"allow"`**, `ask()` returns without suspending. The tool proceeds.

5. **If any pattern yields `"ask"`**, a `Deferred<void, RejectedError | CorrectedError>` is created. The `Request` is added to the `pending` map, and `Event.Asked` is published on the bus. The Effect fiber awaits the deferred.

6. **The client receives `permission.asked` over SSE** and presents the request to the user. The user chooses `"once"`, `"always"`, or `"reject"` and POSTs to `/permission/reply`.

7. **`Permission.Service.reply()` is called.** It looks up the pending entry, publishes `Event.Replied`, then branches:
   - `"reject"` — fails the deferred with `RejectedError` (or `CorrectedError` if a message was supplied); also cancels every other pending request from the same `sessionID`.
   - `"once"` — succeeds the deferred; no persistence.
   - `"always"` — succeeds the deferred; pushes each `always` pattern into the in-memory `approved` list; re-evaluates any other pending requests from the same session that now pass, auto-resolving them.

8. **Persistence.** When `"always"` is chosen, the updated `approved` ruleset is written back to `PermissionTable` for the current project. On next instance boot the row is reloaded, so approved patterns survive restarts.

9. **Finalizer.** When the Effect scope is torn down (`Instance.dispose()`), an `addFinalizer` callback fails every remaining `pending` deferred with `RejectedError`, preventing leaked fibers.

---

## Source Files

| File | Key functions / exports |
|---|---|
| `src/permission/index.ts` | `Permission.Action`, `Permission.Rule`, `Permission.Ruleset`, `Permission.Request`, `Permission.Reply`, `Permission.Approval`, `Permission.Event`, `Permission.Service`, `Permission.layer`, `Permission.evaluate()` |
| `src/permission/evaluate.ts` | `evaluate(permission, pattern, ...rulesets): Rule` — pure rule evaluation using `findLast` |
| `src/permission/schema.ts` | `PermissionID` — branded ascending identifier type |
| `src/session/session.sql.ts` | `PermissionTable` — Drizzle table for project-level persisted approvals |
| `src/util/wildcard.ts` | `Wildcard.match(subject, pattern)` — glob matching used by `evaluate` |
| `src/server/routes/permission.ts` | HTTP routes: `POST /permission/reply`, `GET /permission/list` |

---

## See Also

- [Tool System](tool-system.md)
- [Session System](session-system.md)
- [Permission and Approval Gating](../concepts/permission-and-approval-gating.md)
- [Provider Tool Plugin Interaction Model](../syntheses/provider-tool-plugin-interaction-model.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Request To Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
