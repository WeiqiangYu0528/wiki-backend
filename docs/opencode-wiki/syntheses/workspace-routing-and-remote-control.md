# Workspace Routing and Remote Control

## Overview

This synthesis explains how OpenCode routes a request to the correct execution
context — local or remote — based on the `workspaceID` field carried by
`Session.Info`. It covers the decision point where local execution goes directly
to `Instance.provide()`, while remote execution is forwarded through a
control-plane adaptor that synchronizes state back over SSE. It also documents
the teardown path that fires when a remote instance is disposed.

Understanding this routing matters because a request that appears to fail may
actually have been forwarded to a remote workspace that is unreachable, or may
have succeeded remotely but failed to propagate its result back over the SSE
sync channel. Without knowing where the routing decision is made and what data
it depends on, debugging these cases requires re-reading the entire server stack
from scratch.

## Systems Involved

| System | Contribution |
| --- | --- |
| [Control Plane and Workspaces](../entities/control-plane-and-workspaces.md) | Workspace records, adaptors, remote routing table, and SSE sync loop |
| [Project and Instance System](../entities/project-and-instance-system.md) | `Instance.provide`, `InstanceContext`, per-directory cache, and `GlobalBus` teardown |
| [Server API](../entities/server-api.md) | Hono HTTP server, route registration, and workspace-aware request dispatch |
| [Session System](../entities/session-system.md) | `Session.Info` carrying `workspaceID` field that drives the routing decision |
| [Bus System](../entities/storage-and-sync.md) | `GlobalBus.emit` for cross-instance events; per-instance `Bus` for session/message events |

## Step-by-Step Flow

### 1. Request Arrives at Hono Server

A client (TUI, web, desktop, SDK) sends an HTTP request to the running server.
The Hono router matches the route and extracts path/query parameters, including
the session identifier (`sessionID` or `slug`) from the URL path segment.

### 2. Session Read from DB

The workspace-aware routing middleware reads the target session by calling
`Session.fromRow(row)` on the Drizzle query result. The critical mapping is:

```
row.workspace_id  →  Session.Info.workspaceID
null              →  undefined   (triggers local path)
"ws_xxxx"         →  WorkspaceID (triggers remote path)
```

`fromRow` implements this as `row.workspace_id ?? undefined`, so a SQL `NULL`
value becomes TypeScript `undefined`. This null-coalescing step is the gateway
to the entire routing decision.

### 3. `workspaceID` Presence Check

The router inspects `session.workspaceID`:

- **`workspaceID === undefined`** — session is local. Execution proceeds via
  `Instance.provide({ directory: session.directory })`. No control-plane lookup.
- **`workspaceID` is a `WorkspaceID` branded string** — session is remote.
  The router looks up the adaptor registered for that workspace ID in the
  control-plane workspace table.

The `WorkspaceID` type is a branded string defined in `control-plane/schema.ts`.
Its presence is sufficient to trigger the remote path; no other field is checked.

### 4. Local Path: `Instance.provide` and Context Resolution

`Instance.provide({ directory })` is called:

**Cache hit path** — returns the existing `InstanceContext` immediately from
`cache: Map<string, Promise<InstanceContext>>`. No DB query occurs. This is the
common case for sessions in an already-active directory.

**Cache miss path** — `boot({ directory })` is called:
- `Project.fromDirectory(directory)` queries `ProjectTable`, matching on the
  directory path prefix among known `sandboxes`. If no row found, a new
  `Project.Info` row is upserted with a generated `ProjectID`.
- The git worktree root is resolved by walking parent directories for `.git`.
  Falls back to `"/"` for non-git directories.
- `InstanceContext = { directory, worktree, project }` is constructed.
- The result is stored in the cache via `track(directory, context)`.
- `Context.create<InstanceContext>("instance")` exposes the context via Node
  Async Local Storage. All downstream code in the same async chain can call
  `Instance.directory`, `Instance.worktree`, and `Instance.project` without
  receiving the context explicitly.

### 5. Remote Path: Control-Plane Adaptor Lookup

The router looks up the adaptor for `workspaceID` in the control-plane workspace
table. The adaptor is a typed proxy object constructed from the workspace record.
The record contains:
- The remote server's base URL (e.g., `https://remote.example.com:3000`)
- An auth token for authenticating the forwarded request

If no adaptor entry exists for the given `WorkspaceID`, the router returns a
`503 Service Unavailable` response immediately — no forwarding attempt is made.

### 6. Remote Path: Request Forwarding

The adaptor constructs an outgoing HTTP request to the remote OpenCode server:
- All relevant headers are forwarded, including the auth token from the
  workspace record (added as an `Authorization` header or equivalent).
- The original request body is forwarded verbatim.
- The adaptor acts as a transparent proxy: the local caller receives a response
  with the same HTTP status code and body shape as if the request had been
  handled locally.

### 7. SSE Sync Layer: Remote-to-Local Event Bridging

The remote server processes the forwarded request and emits `Bus` events locally
(`session.updated`, `message.updated`, `permission.asked`). The SSE sync channel
between the two servers carries these serialized `BusEvent` JSON frames back to
the originating local server.

The local server re-publishes the received frames on the local `Bus` via
`Bus.publish`. This ensures that clients connected to the local server see remote
session and message updates in real time with no special client-side knowledge of
the remote topology — from the client's perspective, it is always talking to one
server with one unified SSE stream.

### 8. `GlobalBus.emit` for Cross-Instance Coordination

When a local instance needs to signal state changes to peer servers or to the
control plane, it calls `GlobalBus.emit("event", { directory, payload })`. The
payload is a typed event object. The most common cross-instance event is
`server.instance.disposed`, carrying `{ directory: string }` as both the routing
key and the payload property. `GlobalBus` is a module-level singleton defined in
`bus/global.ts`, separate from the per-instance `Bus`.

### 9. Teardown: `server.instance.disposed` Event

When an `InstanceContext` is being torn down (worktree deleted, explicit dispose
call, or server SIGINT), `instance.ts` calls the module-level `emit(directory)`:
- Publishes `server.instance.disposed` on `GlobalBus` with the directory.
- Subscribers — workspace sync loop, proxy adaptors, `State` singleton store —
  receive this event and clean up their forwarding state.
- `State.dispose(directory)` is called, which walks `Map<string, Map<any, Entry>>`
  and invokes every `Entry.dispose(state) => Promise<void>` registered under
  that directory.

### 10. Cache Eviction

After teardown, the `cache` entry for the disposed directory is removed from
`Map<string, Promise<InstanceContext>>`. Subsequent requests to the same directory
trigger a fresh `boot()` call.

A race condition exists: two concurrent requests arriving during eviction may
result in one request operating on a stale context. The `track()` function uses a
Promise to serialize the boot step, which mitigates but does not fully eliminate
this race.

### 11. Client Receives Synchronized State

Regardless of whether execution was local or remote, the client receives the same
SSE stream of serialized `BusEvent` JSON:
- `session.updated` carrying full `Session.Info`
- `message.updated` carrying full `MessageV2.WithParts`
- `permission.asked` carrying `Permission.Request`

The routing layer is entirely transparent to clients. They subscribe to the SSE
endpoint on the local server and see a unified event stream with no per-client
filtering at the Bus layer. Filtering by session is done client-side on the
`payload.sessionID` field of each event.

## Data at Each Boundary

| Boundary | Data Crossing | Key Types |
| --- | --- | --- |
| Client → Hono router | HTTP request with session identifier | Path param `sessionID` or `slug`; query params for pagination |
| Router → routing decision | Session record from DB | `Session.Info` with `workspaceID: WorkspaceID \| undefined` (from `row.workspace_id ?? undefined`) |
| Local path → `Instance.provide` | Directory string | `{ directory: string }` extracted from `session.directory` |
| `Instance.provide` → caller | Live instance context | `InstanceContext { directory: string, worktree: string, project: Project.Info }` |
| Remote path → adaptor | Workspace identity | `WorkspaceID` branded string used as lookup key in workspace table |
| Adaptor → remote server | Full HTTP request | Forwarded headers (auth token), original request body |
| Remote server → SSE sync channel | Bus events as SSE frames | Serialized `BusEvent` JSON: `{ type: string, payload: unknown }` |
| SSE sync channel → local `Bus` | Re-published bus events | `BusEvent` payloads re-emitted via `Bus.publish` on local server |
| `GlobalBus.emit` → subscribers | Cross-instance notification | `{ directory: string, payload: { type: "server.instance.disposed", properties: { directory } } }` |
| `State.dispose` → entry dispose functions | Teardown callbacks | `Entry.dispose(state: any) => Promise<void>` per registered singleton |
| Teardown → cache | Cache invalidation | Directory string key removed from `Map<string, Promise<InstanceContext>>` |

## Failure Points

| Stage | What Can Fail | Mechanism | Observable Symptom |
| --- | --- | --- | --- |
| Session read | `Session.Info` not found in `SessionTable` | `NotFoundError` from `Database` | 404 from router; client sees not-found error |
| `fromRow` mapping | `workspace_id` column has unexpected non-null junk value | `WorkspaceID` parse fails at Zod boundary | Schema parse error thrown; request returns 500 |
| Routing decision | `workspaceID` present but workspace record missing | Adaptor lookup returns null | Request returns 503; client receives "workspace not found" |
| Remote adaptor | Remote server unreachable (network timeout, wrong URL) | HTTP connect timeout or DNS failure | Request times out; no SSE events arrive; session frozen |
| Remote adaptor | Auth token expired or invalid | Remote server returns 401 | Adaptor propagates 401 to client; forwarding fails |
| SSE sync channel | Connection dropped mid-stream | TCP teardown while events in flight | Client stops receiving updates; session appears frozen |
| SSE sync channel | Remote emits events faster than local can consume | Buffer overflow in SSE reader | Events dropped; client sees incomplete message history |
| `GlobalBus.emit` | No subscribers registered (sync loop not started) | `emit` iterates empty subscriber set | Teardown event lost; stale cache entries persist |
| `boot()` local path | `Project.fromDirectory` fails (permission denied) | `fs.stat` throws `EACCES` or `ENOENT` | Instance never created; request returns error |
| `boot()` local path | Concurrent boots for same directory before cache entry set | Two Promises racing to insert same cache key | One `boot()` abandoned; `track()` ordering determines winner |
| Cache eviction race | Two requests for a directory being disposed | First gets stale context; second triggers fresh boot | One request operates on deleted worktree; tool calls fail with `ENOENT` |
| State teardown | `Entry.dispose` throws for a registered singleton | Exception propagates through `State.dispose` loop | Subsequent dispose calls for other entries in same directory may be skipped |

## Source Evidence

| File | Function / Symbol | Why It Matters |
| --- | --- | --- |
| `packages/opencode/src/project/instance.ts` | `Instance.provide`, `boot`, `track`, `emit`, `cache` | Core routing decision; cache management; `GlobalBus.emit` for `server.instance.disposed` |
| `packages/opencode/src/project/state.ts` | `State.create`, `State.dispose`, `Entry` interface | Per-directory lazy singleton store; teardown callbacks |
| `packages/opencode/src/session/index.ts` | `Session.Info`, `Session.fromRow`, `toRow` | `workspaceID` field; `fromRow` null-coalescing from `row.workspace_id ?? undefined` |
| `packages/opencode/src/control-plane/workspace.ts` | Workspace adaptor construction, SSE sync loop | Remote proxy adaptor; event re-publishing from remote to local `Bus` |
| `packages/opencode/src/control-plane/schema.ts` | `WorkspaceID` branded type | Branded string type used as routing key |
| `packages/opencode/src/server/server.ts` | Hono server construction, middleware registration | Route mounting; workspace-aware middleware integration |
| `packages/opencode/src/server/router.ts` | Workspace-aware routing logic | Local vs. remote dispatch; `workspaceID` presence check |
| `packages/opencode/src/bus/global.ts` | `GlobalBus`, `GlobalBus.emit`, `GlobalBus.subscribe` | Cross-instance event singleton; teardown notification channel |

## See Also

- [Control Plane and Workspaces](../entities/control-plane-and-workspaces.md)
- [Project and Instance System](../entities/project-and-instance-system.md)
- [Server API](../entities/server-api.md)
- [Session System](../entities/session-system.md)
- [Multi Client Product Architecture](multi-client-product-architecture.md)
- [Request to Session Execution Flow](request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
