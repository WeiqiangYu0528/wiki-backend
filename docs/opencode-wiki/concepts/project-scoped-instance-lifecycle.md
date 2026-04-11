# Project Scoped Instance Lifecycle

## Overview

Every project directory gets exactly one `InstanceContext` for the lifetime of the server process. This context bundles together the canonical directory path, the worktree (or sandbox) path, and the `Project.Info` metadata discovered from the filesystem. All services that need project-local state — sessions, plugins, the permission store, file watchers — operate inside this context. The context is created on first access, cached by canonical path, and torn down explicitly when the instance is disposed.

The single-instance-per-directory guarantee means that two concurrent requests for the same project share setup cost and share all mutable project state. It also means disposal is unambiguous: there is exactly one thing to dispose.

## Mechanism

### InstanceContext shape

`InstanceContext` is defined as a plain interface:

```typescript
interface InstanceContext {
  directory: string   // canonical absolute path
  worktree: string    // sandbox or worktree root
  project: Project.Info
}
```

`Project.Info` carries the metadata discovered by `Project.fromDirectory()`: VCS root, project name, any sandbox configuration, and related fields.

### Cache keyed by canonical path

`Instance.provide()` is the only public entry point for entering an instance context. It calls `Filesystem.resolve(input.directory)` to canonicalize the path (resolving symlinks, `..` components, and relative paths) before looking up the cache. This ensures that `/home/user/myproject` and `/home/user/myproject/` and a symlink pointing to the same directory all map to a single cache entry.

```
Instance.provide({ directory, init?, fn })
  -> Filesystem.resolve(directory)          // canonical key
  -> cache.get(key) or track(key, boot())   // create if absent
  -> context.provide(ctx, fn)               // run fn in async context
```

If no entry exists, `track()` stores the pending `Promise<InstanceContext>` in the cache immediately (before the promise resolves), so a second concurrent call for the same directory reuses the in-flight promise rather than starting a second boot.

### Boot sequence

`boot()` runs the initialization sequence:

1. If `project` and `worktree` are supplied (pre-known), construct `InstanceContext` directly.
2. Otherwise call `Project.fromDirectory(input.directory)` which walks the filesystem to find the VCS root and reads any OpenCode project config. The result provides both `project` (the `Project.Info`) and `sandbox` (used as `worktree`).
3. Call `context.provide(ctx, init?)` to make the resolved context available to all async code running under the `AsyncLocalStorage` slot named `"instance"`.
4. Run the optional `init()` callback inside the context. This is where `InstanceBootstrap` registers plugins, file watchers, VCS integration, and snapshot services.

### Async context propagation

`Context.create("instance")` creates an `AsyncLocalStorage`-backed slot. Any code running inside a `context.provide(ctx, fn)` call can retrieve the current `InstanceContext` by calling `Instance.get()` (or the equivalent context read). This propagates through `await`, `Promise.all`, and Effect fibers without explicit parameter threading.

The Effect service layer mirrors this through `InstanceState`, which surfaces the same context as an Effect `Layer`. Server handlers, session runners, and tool implementations all access project state through this mechanism.

### Disposal

`disposeInstance(directory)` removes the cache entry and runs the cleanup registered in `disposal.all`. Before returning, it emits `server.instance.disposed` on `GlobalBus`:

```typescript
GlobalBus.emit("event", {
  directory,
  payload: { type: "server.instance.disposed", properties: { directory } }
})
```

Connected clients subscribe to `GlobalBus` events through the SSE stream and can react to disposal by detaching or showing a reconnect prompt. The `disposal.all` promise coordinates any outstanding async teardown (closing database connections, stopping file watchers, flushing snapshots).

### Error recovery in the cache

`track()` installs a `.catch()` on the stored promise. If `boot()` rejects, the cache entry is deleted for that directory, allowing a subsequent call to `Instance.provide()` to retry initialization from scratch rather than permanently caching a failure.

## Invariants

1. At most one `InstanceContext` is live per canonical directory at any time. The cache stores a `Promise<InstanceContext>`, not the resolved value, so concurrent first-access requests share the same boot sequence.
2. `Filesystem.resolve()` is called before every cache lookup. Two paths that resolve to the same canonical path always share one instance.
3. `boot()` failures do not permanently poison the cache. The error handler in `track()` removes the failed entry so recovery is possible.
4. The async context is always entered via `context.provide()`. No code receives `InstanceContext` as a raw import-level singleton; the context must be active on the call stack.
5. `GlobalBus.emit("server.instance.disposed")` is the last action before teardown completes. Any code that reacts to disposal (client detach, secondary instance cleanup) observes the event after the context is no longer active.

## Source Evidence

| File | What it confirms |
| --- | --- |
| `packages/opencode/src/project/instance.ts` | `InstanceContext` interface, `cache` Map, `Filesystem.resolve()` call, `boot()` function, `track()` error handler, `GlobalBus.emit("server.instance.disposed")`, `disposal.all` |
| `packages/opencode/src/project/project.ts` | `Project.fromDirectory()` implementation; worktree/sandbox discovery |
| `packages/opencode/src/util/context.ts` | `Context.create()` wrapping `AsyncLocalStorage` |
| `packages/opencode/src/effect/instance-state.ts` | `InstanceState` Effect layer surfacing instance context to the service graph |
| `packages/opencode/src/project/bootstrap.ts` | `InstanceBootstrap` registering plugins, VCS, file watchers, snapshots inside the instance context |
| `packages/opencode/src/bus/global.ts` | `GlobalBus` process-level event emitter used for `server.instance.disposed` |

## See Also

- [Client Server Agent Architecture](client-server-agent-architecture.md)
- [Plugin Driven Extensibility](plugin-driven-extensibility.md)
- [Project and Instance System](../entities/project-and-instance-system.md)
- [Workspace Routing and Remote Control](../syntheses/workspace-routing-and-remote-control.md)
- [Request to Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
