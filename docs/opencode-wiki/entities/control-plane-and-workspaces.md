# Control Plane and Workspaces

## Overview

The control plane and workspace subsystem lets OpenCode route HTTP requests either to local project instances running in the same process or to remote workspaces running in separate processes (such as git worktrees). This is the architectural layer that makes OpenCode multi-workspace aware: a single server can simultaneously host several independent project contexts and proxy traffic between them transparently.

The key concepts are:

- A **Workspace** is a database record that describes where a project context lives (`type`, `directory`, `branch`, `extra`).
- An **Adaptor** is the interface that the control plane uses to create, configure, and proxy requests to a workspace of a given type.
- The **`WorkspaceRouterMiddleware`** in `server/router.ts` is the HTTP-level gating layer that inspects every incoming request, looks up the target workspace, and routes accordingly.
- **SSE (`sse.ts`)** provides the event stream parsing logic used when a remote workspace pushes events back to the control plane.

---

## Key Types

### `WorkspaceInfo` / `Workspace.Info`

```ts
// src/control-plane/types.ts
export const WorkspaceInfo = z.object({
  id:        WorkspaceID.zod,
  type:      z.string(),          // e.g. "worktree" — determines which adaptor handles it
  branch:    z.string().nullable(),
  name:      z.string().nullable(),
  directory: z.string().nullable(), // resolved filesystem path for local workspaces
  extra:     z.unknown().nullable(), // adaptor-specific configuration blob
  projectID: ProjectID.zod,
})
```

`directory` is `null` for remote workspace types that do not have a local path. `extra` is a free-form JSON field that adaptors can use to store their own configuration.

---

### `WorkspaceID`

```ts
// src/control-plane/schema.ts
const workspaceIdSchema = Schema.String.pipe(Schema.brand("WorkspaceID"))

export const WorkspaceID = workspaceIdSchema.pipe(
  withStatics((schema) => ({
    make:      (id: string) => schema.makeUnsafe(id),
    ascending: (id?: string) => schema.makeUnsafe(Identifier.ascending("workspace", id)),
    zod:       Identifier.schema("workspace").pipe(z.custom<WorkspaceID>()),
  })),
)
```

A branded string type guaranteed to have the `workspace_` prefix via the `Identifier.ascending()` generator. Used as primary key in `WorkspaceTable` and as the `?workspace=` query parameter on routed HTTP requests.

---

### `Adaptor`

```ts
// src/control-plane/types.ts
export type Adaptor = {
  configure(input: WorkspaceInfo): WorkspaceInfo | Promise<WorkspaceInfo>
  create(input: WorkspaceInfo, from?: WorkspaceInfo): Promise<void>
  remove(config: WorkspaceInfo): Promise<void>
  fetch(config: WorkspaceInfo, input: RequestInfo | URL, init?: RequestInit): Promise<Response>
}
```

The adaptor pattern decouples the control plane from workspace implementation details. The `fetch` method is the core: it proxies an HTTP request to wherever the workspace actually runs. The only built-in adaptor today is `WorktreeAdaptor` (registered under the `"worktree"` type), which boots a child process server in the worktree directory and forwards requests to it via HTTP.

---

### `Workspace.Event`

```ts
export const Event = {
  Ready:  BusEvent.define("workspace.ready",  z.object({ name: z.string() })),
  Failed: BusEvent.define("workspace.failed", z.object({ message: z.string() })),
}
```

Published on the `GlobalBus` when an adaptor finishes provisioning (`Ready`) or encounters a fatal error (`Failed`).

---

### Router rule type

```ts
// src/server/router.ts
type Rule = {
  method?:  string
  path:     string
  exact?:   boolean
  action:  "local" | "forward"
}
```

Rules control whether a request to a known workspace should be served from the local cached state (`"local"`) or forwarded to the remote adaptor (`"forward"`). The `local()` function evaluates the rule list using method + path prefix matching. Currently, `GET /session` is served locally from cache while `POST /session/status` is forwarded.

---

## Architecture

```
src/control-plane/
  workspace.ts       ← Workspace namespace: create, get, list, fromRow, Event
  schema.ts          ← WorkspaceID branded type
  types.ts           ← WorkspaceInfo schema, Adaptor interface
  workspace.sql.ts   ← WorkspaceTable Drizzle schema
  sse.ts             ← parseSSE() — stream reader for remote workspace event relay
  adaptors/
    index.ts         ← getAdaptor(type), installAdaptor(type, adaptor) registry
    worktree.ts      ← WorktreeAdaptor — local git worktree workspace implementation

src/server/
  router.ts          ← WorkspaceRouterMiddleware — HTTP routing logic
```

`workspace.ts` owns the database layer (CRUD on `WorkspaceTable`) and the lifecycle events. `router.ts` sits at the HTTP boundary and is the only code that reads the `?workspace=` query parameter or the `x-opencode-directory` header. The adaptor registry in `adaptors/index.ts` is lazy-loaded to avoid pulling adaptor dependencies until a workspace of that type is actually used.

---

## Runtime Behavior

### Request routing — `WorkspaceRouterMiddleware`

1. **Every request** below the workspace-aware mount point passes through `WorkspaceRouterMiddleware`.

2. **Directory resolution.** The middleware reads the target directory from `?directory=` query param, the `x-opencode-directory` header, or falls back to `process.cwd()`. The value is URI-decoded and resolved to an absolute canonical path.

3. **Workspace parameter check.** If no `?workspace=` query parameter is present, the request is for the **project workspace** — the middleware calls `Instance.provide({ directory, init: InstanceBootstrap, fn })` and delegates to `InstanceRoutes`. This is the common case for the TUI and CLI clients.

4. **Workspace lookup.** If `?workspace=` is present, `Workspace.get(workspaceID)` queries `WorkspaceTable`. If no row is found, a 500 response is returned immediately.

5. **Local worktree workspace.** If `workspace.type === "worktree"` and `workspace.directory` is set, the middleware calls `Instance.provide({ directory: workspace.directory, ... })` and serves the request locally, preserving the Bun websocket environment needed for PTY upgrades.

6. **Remote workspace — local rules.** If the workspace type is not `"worktree"`, the `local()` function is consulted. Paths configured as `"local"` (e.g. `GET /session`) are served directly from the current process without an instance context, because the data is cached locally.

7. **Remote workspace — proxy.** For all other paths, `getAdaptor(workspace.type)` loads the adaptor, then `adaptor.fetch(workspace, pathname+search, init)` proxies the request to the remote process. Request body is passed as `ArrayBuffer` and the `x-opencode-workspace` header is stripped before forwarding.

---

### Workspace creation — `Workspace.create()`

1. Generates an ascending `WorkspaceID`.
2. Calls `adaptor.configure(input)` to let the adaptor fill in defaults (name, directory, extra).
3. Inserts the row into `WorkspaceTable`.
4. Calls `adaptor.create(config)` to provision the workspace (e.g. create the git worktree, run `commands.start`).
5. Returns the completed `Workspace.Info`.

---

### SSE parsing — `parseSSE()`

```ts
export async function parseSSE(
  body:    ReadableStream<Uint8Array>,
  signal:  AbortSignal,
  onEvent: (event: unknown) => void,
): Promise<void>
```

Used by the `WorktreeAdaptor` when it needs to relay events from a child-process server back to the parent. The function reads chunks from the stream, accumulates a line buffer, splits on `\n\n` SSE boundaries, and calls `onEvent` with the parsed JSON payload. Non-JSON payloads are wrapped in a synthetic `{ type: "sse.message" }` envelope. The `retry:` field from the SSE stream is respected and the `id:` field is tracked for reconnect scenarios.

---

### Adaptor registry — `getAdaptor()` / `installAdaptor()`

```ts
// src/control-plane/adaptors/index.ts
const ADAPTORS: Record<string, () => Promise<Adaptor>> = {
  worktree: lazy(async () => (await import("./worktree")).WorktreeAdaptor),
}

export function getAdaptor(type: string): Promise<Adaptor>
export function installAdaptor(type: string, adaptor: Adaptor)
```

Adaptors are registered by string type name. `lazy()` ensures each adaptor module is imported at most once. `installAdaptor` is experimental and intended for testing; it bypasses the TypeScript type constraints.

---

## Source Files

| File | Key functions / exports |
|---|---|
| `src/control-plane/workspace.ts` | `Workspace.create()`, `Workspace.get()`, `Workspace.list()`, `Workspace.Event.Ready/Failed`, `Workspace.Info` |
| `src/control-plane/schema.ts` | `WorkspaceID` branded type, `WorkspaceID.ascending()`, `WorkspaceID.make()` |
| `src/control-plane/types.ts` | `WorkspaceInfo` schema, `Adaptor` interface |
| `src/control-plane/workspace.sql.ts` | `WorkspaceTable` Drizzle schema |
| `src/control-plane/sse.ts` | `parseSSE(body, signal, onEvent)` — SSE stream reader |
| `src/control-plane/adaptors/index.ts` | `getAdaptor(type)`, `installAdaptor(type, adaptor)` |
| `src/control-plane/adaptors/worktree.ts` | `WorktreeAdaptor` — local git worktree adaptor implementation |
| `src/server/router.ts` | `WorkspaceRouterMiddleware` — HTTP routing between local and remote workspaces |

---

## See Also

- [Server API](server-api.md)
- [Project and Instance System](project-and-instance-system.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Workspace Routing and Remote Control](../syntheses/workspace-routing-and-remote-control.md)
- [Request To Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
