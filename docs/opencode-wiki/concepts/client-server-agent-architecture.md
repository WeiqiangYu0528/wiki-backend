# Client Server Agent Architecture

## Overview

OpenCode is structured as a local server process that multiple client surfaces attach to over HTTP and Server-Sent Events. Running `opencode serve` starts a Hono HTTP server; the TUI, web interface, desktop application, Slack integration, and programmatic SDK all connect to that server as thin clients. The server is the sole owner of agent state: sessions, providers, permissions, and the project instance context. Clients are display-only renderers that send requests and stream events back to the user.

This design makes the agent runtime reachable from any surface without duplicating session logic. The TUI is not special — `AttachCommand` connects over the network exactly as any other client would. If the server is already running for a project directory, attaching is instant; if not, the TUI starts the server itself and then connects.

## Mechanism

### Server startup

`ServeCommand` initializes the Hono HTTP application and registers route handlers covering sessions, providers, permissions, tools, and file operations. The server binds to a local port (default `4096`) and writes a socket file so other processes can discover it. OpenAPI schema generation happens at startup so every endpoint has a typed contract that the SDK and clients consume.

`Instance.provide()` is called during startup with the target project directory. It canonicalizes the path via `Filesystem.resolve()`, looks up or creates the cached `InstanceContext`, and runs the rest of initialization inside that context. This means all downstream services — plugins, the session store, the permission table — operate in the scope of a single project directory.

### Client connection model

Clients communicate with the server through two channels:

1. **REST endpoints** — HTTP POST/GET calls for actions such as creating a session, submitting a message, or fetching provider configuration. These follow request/response semantics.
2. **SSE stream** — A persistent `GET /bus` endpoint delivers a real-time event stream to every connected client. Any state change on the server (new message part, permission request, session status update) is serialized as a `Bus` event and pushed through this channel.

The `Bus` subsystem is the internal pub/sub backbone. When a session produces a new output token, the session code publishes a `Session.Event.PartDelta` event to the bus. The SSE handler subscribes to the bus and forwards every event to all connected clients. Clients render whatever arrives; they never hold authoritative state.

### Event propagation

`GlobalBus` is the process-level event emitter used for cross-instance signaling (for example `server.instance.disposed`). The per-request `Bus` operates within the Effect service layer and is scoped to a running instance. Plugin errors, permission requests, and session lifecycle events all flow through `Bus.publish()` and reach connected clients without the server needing to know which surfaces are active.

### TUI attach flow

`AttachCommand` checks whether a server is already listening on the project's socket. If one is found, it connects immediately. If not, it forks the server in the background, waits for readiness, and then connects. From the perspective of the server, a TUI session is indistinguishable from an SDK session: both are HTTP clients reading from the SSE stream and issuing REST requests.

### State ownership

The server owns:
- All `Session` records (persisted to SQLite via `SessionTable`)
- Provider configuration and credential resolution (`Auth`)
- The active permission ruleset and persistent approvals (`PermissionTable`)
- The project `InstanceContext` (directory, worktree, project metadata)

Clients own only transient UI state: scroll position, focused pane, user input buffer. No session or agent data is stored client-side.

## Invariants

1. Exactly one `InstanceContext` exists per canonical project directory at any moment. Concurrent attach requests for the same path share the cached promise returned by `Instance.provide()`.
2. Every state change visible to a client was published through `Bus`. There is no out-of-band mutation path that bypasses the event stream.
3. The server can run headless (no TUI attached) indefinitely. Sessions created via the SDK or REST API persist and are visible the moment a TUI client attaches.
4. `AttachCommand` always connects over the network, even when it starts the server itself. There is no "embedded" mode where the TUI runs the agent inline.
5. Disposing an instance via `disposeInstance()` emits `server.instance.disposed` on `GlobalBus` before tearing down the context, giving clients a chance to detach cleanly.

## Source Evidence

| File | What it confirms |
| --- | --- |
| `packages/opencode/src/project/instance.ts` | `Instance.provide()` cache keyed by `Filesystem.resolve()`, `boot()` calling `Project.fromDirectory()`, `GlobalBus.emit("server.instance.disposed")` |
| `packages/opencode/src/session/index.ts` | `Bus` publish calls for session events; `SessionTable` as the persistence layer |
| `packages/opencode/src/permission/index.ts` | `Permission.Event.Asked` published on the bus; `PermissionTable` for persisted approvals |
| `packages/opencode/src/plugin/index.ts` | `publishPluginError()` routes errors through the bus; plugin lifecycle wired to instance startup |
| `packages/opencode/src/provider/provider.ts` | Provider construction scoped per instance; `Auth` and `Config` resolved at server startup |

## See Also

- [Project Scoped Instance Lifecycle](project-scoped-instance-lifecycle.md)
- [Provider Agnostic Model Routing](provider-agnostic-model-routing.md)
- [Permission and Approval Gating](permission-and-approval-gating.md)
- [Plugin Driven Extensibility](plugin-driven-extensibility.md)
- [Server API](../entities/server-api.md)
- [Multi Client Product Architecture](../syntheses/multi-client-product-architecture.md)
- [Workspace Routing and Remote Control](../syntheses/workspace-routing-and-remote-control.md)
- [Request to Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
