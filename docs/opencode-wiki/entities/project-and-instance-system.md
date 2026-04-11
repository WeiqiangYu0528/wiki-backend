# Project and Instance System

## Overview

The project and instance system provides the foundational runtime context for every operation in OpenCode. It answers a single question: given a filesystem directory, what project does it belong to, and what associated resources (worktree, state, services) should be active while code runs there?

An **Instance** is the live runtime binding of a directory to a `Project.Info` record plus a resolved worktree path. Instances are cached in a module-level `Map` keyed by resolved directory path, so a second call to `Instance.provide()` for the same directory reuses the already-booted context rather than re-querying the database.

The system uses Node's Async Local Storage (via the `Context` utility) to thread instance context through async call chains without passing it explicitly in every function argument. Any code that reads `Instance.directory`, `Instance.worktree`, or `Instance.project` is implicitly receiving the context set by the nearest enclosing `Instance.provide()` call.

---

## Key Types

### `InstanceContext`

```ts
export interface InstanceContext {
  directory: string        // absolute resolved path to the working directory
  worktree:  string        // absolute path to the git worktree root
                           // (may equal "/" for non-git projects)
  project:   Project.Info  // database record describing the project
}
```

This is the shape stored in ALS and returned by `Instance.current`. Every accessor (`Instance.directory`, `Instance.worktree`, `Instance.project`) just destructures this object.

---

### `Project.Info`

```ts
// src/project/project.ts
export const Info = z.object({
  id:        ProjectID.zod,
  worktree:  z.string(),
  vcs:       z.literal("git").optional(),   // set when git repo detected
  name:      z.string().optional(),
  icon:      z.object({
    url:      z.string().optional(),
    override: z.string().optional(),
    color:    z.string().optional(),
  }).optional(),
  commands:  z.object({
    start: z.string().optional(),    // startup script run when creating a new workspace
  }).optional(),
  time: z.object({
    created:     z.number(),
    updated:     z.number(),
    initialized: z.number().optional(),
  }),
  sandboxes: z.array(z.string()),    // active worktree directory paths for this project
})
```

`sandboxes` holds the list of active sandbox (worktree) directory paths registered under this project. `commands.start` is run when a new workspace is provisioned via the `worktree` adaptor.

---

### Internal `State.Entry`

```ts
// src/project/state.ts
interface Entry {
  state:    any
  dispose?: (state: any) => Promise<void>
}
```

`State` maintains a two-level `Map<string, Map<any, Entry>>` where the outer key is the instance directory path and the inner key is the `init` function reference. This enables per-directory lazy singletons that are all torn down together when the instance is disposed.

---

## Architecture

```
src/project/
  instance.ts    ← Instance object: provide, bind, reload, dispose, disposeAll
  project.ts     ← Project.Info type, Project.fromDirectory(), DB queries, Event.Updated bus event
  state.ts       ← State.create() / State.dispose() — per-directory lazy singleton store
  bootstrap.ts   ← InstanceBootstrap: Effect layer initialization run once per instance

src/util/
  context.ts     ← Context.create<T>() — thin ALS wrapper used by instance.ts
  filesystem.ts  ← Filesystem.resolve(), Filesystem.contains()
  iife.ts        ← iife() utility for IIFE async patterns used in boot()

src/bus/
  global.ts      ← GlobalBus.emit() for cross-instance events like server.instance.disposed

src/effect/
  instance-registry.ts  ← disposeInstance(): tears down Effect runtime for a directory
  instance-state.ts     ← InstanceState.make() / InstanceState.get() — Effect layer per instance
```

`instance.ts` is intentionally thin. It delegates project resolution to `Project.fromDirectory()`, state management to `State`, and Effect-layer teardown to `disposeInstance`. The file owns only the module-level cache map and the ALS context object.

The `cache` is a plain `Map<string, Promise<InstanceContext>>`. Storing promises rather than resolved values means concurrent `provide()` calls for the same directory during boot all await the same promise and share the result — no thundering herd.

---

## Runtime Behavior

### Instance boot — `Instance.provide()`

1. **Caller invokes `Instance.provide({ directory, init?, fn })`.**

2. **Directory is resolved** with `Filesystem.resolve()` to an absolute, canonical path. This becomes the cache key.

3. **Cache lookup.** If `cache.get(directory)` already holds a `Promise<InstanceContext>`, it is awaited directly. No second boot occurs.

4. **Cache miss — `boot()` is called.** If the caller supplied pre-computed `project` and `worktree` values, they are used directly. Otherwise `Project.fromDirectory(directory)` is called: it queries `ProjectTable`, inserting a new row if this directory has never been seen, runs git commands to discover the worktree root, and returns `{ project, sandbox }`.

5. **`context.provide(ctx, init?)` runs.** The `InstanceContext` is pushed into ALS for the current async subtree. The optional `init` callback (typically `InstanceBootstrap`) is awaited inside this context; it installs Effect service layers (Bus, Permission, Config, etc.) scoped to this instance.

6. **`boot()` resolves to `InstanceContext`.** The value is stored via `track()`, which attaches a `.catch` handler to remove the entry from `cache` if boot throws, preventing a stuck promise from permanently blocking future boot attempts.

7. **`fn()` is called** inside `context.provide(ctx, fn)`. All code reachable from `fn` can read `Instance.directory` etc. via ALS.

---

### Instance reload — `Instance.reload()`

1. Calls `State.dispose(directory)` — runs all registered dispose callbacks for that directory in parallel.
2. Calls `disposeInstance(directory)` — tears down the Effect scope.
3. Removes the cache entry so the next `provide()` triggers a fresh boot.
4. Calls `boot()` with the (optionally updated) project/worktree values and inserts the new promise into `cache` via `track()`.
5. **Emits `server.instance.disposed`** on `GlobalBus` so all connected clients know to refresh their state.
6. Returns the new `InstanceContext`.

---

### Instance dispose — `Instance.dispose()`

Must be called inside an active instance context (ALS must be set).

1. Reads `Instance.directory` from ALS.
2. Calls `State.dispose(directory)` — awaits all per-directory dispose callbacks.
3. Calls `disposeInstance(directory)` — tears down Effect scopes and finalizers.
4. Removes the entry from `cache`.
5. Calls `emit(directory)` — publishes `server.instance.disposed` on `GlobalBus`.

---

### Dispose all — `Instance.disposeAll()`

Used during server shutdown to cleanly drain all active instances.

1. Guards against concurrent invocations with the `disposal.all` promise sentinel.
2. Iterates a snapshot of `cache.entries()`.
3. For each entry, awaits the boot promise (catching errors gracefully).
4. Calls `Instance.dispose()` inside the recovered ALS context.
5. Clears `disposal.all` in a `finally` block.

---

### Per-instance state — `Instance.state()`

```ts
Instance.state<S>(
  init:     () => S,
  dispose?: (state: Awaited<S>) => Promise<void>
): () => S
```

Returns a zero-argument getter. The first call for a `(directory, init)` pair runs `init()` and caches the result in `State`. Subsequent calls return the cached value. When `State.dispose(directory)` runs, every registered `dispose` callback for that directory is called in parallel with a 10-second timeout warning.

---

### Path boundary check — `Instance.containsPath()`

```ts
Instance.containsPath(filepath: string): boolean
```

Returns `true` if `filepath` is inside `Instance.directory` OR `Instance.worktree`. Special case: when `worktree === "/"` (non-git project), the worktree check is skipped to prevent accidentally matching every absolute path and bypassing `external_directory` permission gates.

---

### Context capture helpers

- **`Instance.bind(fn)`** — captures the current ALS context and returns a wrapper function that re-enters it. Use for callbacks that fire outside the instance async chain (event emitters, native addons, timers).
- **`Instance.restore(ctx, fn)`** — synchronously runs `fn` inside the given `InstanceContext`. Use to bridge from Effect (which carries context via `InstanceRef`) back to synchronous code that reads from ALS.

---

### `GlobalBus.emit("event")` for `server.instance.disposed`

```ts
function emit(directory: string) {
  GlobalBus.emit("event", {
    directory,
    payload: {
      type: "server.instance.disposed",
      properties: { directory },
    },
  })
}
```

This event is emitted by both `Instance.dispose()` and `Instance.reload()`. Clients subscribed to the global event SSE stream receive it and can invalidate or refresh any cached state tied to that directory.

---

## Multi-instance Caching Behavior

Each distinct resolved directory path gets exactly one cache entry. Two callers providing different but overlapping paths (e.g. a subdirectory and its parent) produce separate instances with independent state. Because the cache stores `Promise<InstanceContext>`, concurrent `provide()` calls during boot coalesce onto the same promise and share the boot result without racing.

If boot fails, `track()` removes the failed promise from `cache`, so the next caller triggers a fresh boot attempt rather than receiving a permanently rejected promise.

---

## Source Files

| File | Key functions / exports |
|---|---|
| `src/project/instance.ts` | `Instance.provide()`, `Instance.reload()`, `Instance.dispose()`, `Instance.disposeAll()`, `Instance.state()`, `Instance.bind()`, `Instance.restore()`, `Instance.containsPath()`, `InstanceContext` interface |
| `src/project/project.ts` | `Project.Info` type, `Project.fromDirectory()`, `Project.fromRow()`, `Project.Event.Updated` bus event |
| `src/project/state.ts` | `State.create()`, `State.dispose()` — per-directory lazy singleton registry with dispose support |
| `src/project/bootstrap.ts` | `InstanceBootstrap` — Effect layer init callback run once per new instance |
| `src/util/context.ts` | `Context.create<T>()` — ALS wrapper used by `instance.ts` |
| `src/util/filesystem.ts` | `Filesystem.resolve()`, `Filesystem.contains()` |
| `src/bus/global.ts` | `GlobalBus.emit("event", ...)` — cross-instance event bus |
| `src/effect/instance-registry.ts` | `disposeInstance(directory)` — tears down Effect runtime |
| `src/effect/instance-state.ts` | `InstanceState.make()`, `InstanceState.get()` — Effect service scoped per instance |

---

## See Also

- [Server API](server-api.md)
- [Control Plane and Workspaces](control-plane-and-workspaces.md)
- [Session System](session-system.md)
- [Permission System](permission-system.md)
- [Plugin System](plugin-system.md)
- [Project Scoped Instance Lifecycle](../concepts/project-scoped-instance-lifecycle.md)
- [Workspace Routing and Remote Control](../syntheses/workspace-routing-and-remote-control.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Request To Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
