# Server API

## Overview

The Server API is OpenCode's HTTP service layer. It exposes the full runtime — sessions, providers, projects, file access, PTY, MCP, configuration, and event streaming — as a Hono-based REST API with OpenAPI documentation. It is the boundary that enables non-TUI clients (GUI applications, web frontends, LAN peers, and remote workspaces) to interact with the same state machine the CLI uses.

The server is not a thin wrapper. It owns credential management endpoints, workspace routing, SSE event buses, mDNS LAN discovery, and response projection — all mounted on a single `Hono` application constructed in `server.ts`.

## Key Types

### `Server.ControlPlaneRoutes` (`server/server.ts`)

The top-level Hono application factory. Returns a fully configured `Hono` instance with the complete middleware stack and all route groups mounted. Exported as `Server.Default` (lazy singleton) for normal operation, or called directly with custom CORS origins when embedding the server.

### `WorkspaceRouterMiddleware` (`server/router.ts`)

A Hono `MiddlewareHandler` that reads the target directory from the request (query param `directory` or header `x-opencode-directory`, defaulting to `process.cwd()`), resolves the appropriate `Instance`, and delegates the request to `InstanceRoutes`. For remote workspaces it forwards the request via the registered adaptor rather than handling it locally.

### `MDNS` (`server/mdns.ts`)

Namespace wrapping `bonjour-service`. Publishes an mDNS/Bonjour HTTP service record so LAN clients can discover the running OpenCode server without manual port configuration. The service name is `opencode-<port>` on host `opencode.local`. Only one service is published at a time; calling `MDNS.publish(port)` with a different port first unpublishes the previous record.

### `initProjectors` (`server/projectors.ts`)

Initializes the `SyncEvent` projection layer at server startup. Registers `sessionProjectors` and a `convertEvent` transform that enriches `session.updated` events with the full `Session.Info` object read from the database before broadcasting to subscribers.

### `errorHandler` (`server/middleware.ts`)

A Hono `ErrorHandler` factory that serializes errors into structured JSON responses. Dispatch table:

| Error type | HTTP status |
|---|---|
| `NotFoundError` | 404 |
| `Provider.ModelNotFoundError` | 400 |
| `ProviderAuthValidationFailed` (name-based) | 400 |
| `Worktree*` errors (name-based) | 400 |
| `Session.BusyError` | 400 |
| `HTTPException` | proxied as-is |
| All other `NamedError` | 500 |
| Unknown errors | 500 with stack trace |

All errors are wrapped in `NamedError.toObject()` so clients receive a consistent `{ name, message, data }` envelope.

## Architecture

### Hono Application Stack

`ControlPlaneRoutes()` assembles the middleware stack in order:

1. **Error handler** — `errorHandler(log)` via `.onError()`, applied globally before any route runs
2. **Basic auth** — optional; enabled when `Flag.OPENCODE_SERVER_PASSWORD` is set. Skips OPTIONS requests to allow CORS preflight
3. **Request logging** — logs method + path on entry; records elapsed time on exit via `log.time()`; skips `/log` path to avoid recursion
4. **CORS** — permissive for `localhost:*`, `127.0.0.1:*`, Tauri origins (`tauri://localhost`, `http://tauri.localhost`, `https://tauri.localhost`), `*.opencode.ai`, and any origins explicitly listed in `opts.cors`
5. **Compression** — `hono/compress` gzip middleware, skipped for SSE endpoints (`/event`, `/global/event`, `/global/sync-event`) and streaming POST bodies (`/session/:id/message`, `/session/:id/prompt_async`)

### Route Groups

After the middleware stack the following route groups are mounted:

| Mount path | Module | Contents |
|---|---|---|
| `/global` | `GlobalRoutes` (`routes/global.ts`) | Global (non-workspace) routes: events, sync events, and cross-workspace queries |
| `/auth/:providerID` `PUT`/`DELETE` | inline in `server.ts` | Set or remove persisted credentials for a provider via `Auth.set`/`Auth.remove` |
| `/doc` `GET` | `openAPIRouteHandler` | Auto-generated OpenAPI 3.1.1 spec from route descriptors |
| `/log` `POST` | inline in `server.ts` | Forward client log entries into the server log stream |
| `/*` (workspace-scoped) | `WorkspaceRouterMiddleware` → `InstanceRoutes` | All instance-scoped routes (see below) |

### Instance-scoped Route Modules (`server/routes/`)

All routes under the workspace middleware are implemented in dedicated modules:

| File | Route area |
|---|---|
| `routes/session.ts` | Session lifecycle: create, list, get, send message, prompt async, abort, status |
| `routes/provider.ts` | List providers and models, resolve model metadata |
| `routes/file.ts` | File tree browsing and content access within the project directory |
| `routes/project.ts` | Project info, initialization, workspace metadata |
| `routes/config.ts` | Read and write project/global configuration |
| `routes/mcp.ts` | MCP server registration, listing, and tool invocation |
| `routes/pty.ts` | PTY (pseudo-terminal) session management: spawn, resize, write, attach |
| `routes/event.ts` | SSE event bus (`/event`) — streams `Bus` events to connected clients |
| `routes/workspace.ts` | Workspace management: list, create worktrees, switch |
| `routes/permission.ts` | Tool permission approval/denial for the current session |
| `routes/question.ts` | Interactive question/answer flow for tool confirmations |
| `routes/tui.ts` | TUI-specific control: attach/detach, screen state |
| `routes/experimental.ts` | Feature-flagged experimental endpoints |
| `routes/global.ts` | Global event stream and sync-event projection endpoints |

### OpenAPI Schema Generation

Every route is annotated with `describeRoute({ summary, description, operationId, responses })` from `hono-openapi`. Input validation uses the `validator()` middleware with Zod schemas. The `/doc` endpoint calls `openAPIRouteHandler(app, { documentation: { info, openapi: "3.1.1" } })` to generate the full spec at request time from accumulated route descriptors. Clients can use this spec for type-safe SDK generation.

### SSE / Real-time Event Transport

Two SSE endpoints handle real-time push to clients:

- **`/event`** (instance-scoped) — streams events from the per-instance `Bus`. Clients subscribe here for session updates, tool calls, message streaming, and assistant responses. Compression is disabled for this path to avoid buffering.
- **`/global/event`** (global) — streams events that span all instances (e.g., workspace changes, global config updates).
- **`/global/sync-event`** — streams projected `SyncEvent` payloads. The `initProjectors()` call in `projectors.ts` ensures events are enriched with full `Session.Info` before broadcast.

SSE responses are not compressed (explicitly excluded in `skipCompress`). Long-running sessions may also use the `wrapSSE` timeout mechanism from the provider layer when streaming model output.

### `WorkspaceRouterMiddleware` — Request Routing Logic (`server/router.ts`)

The middleware resolves the target workspace from the incoming request:

1. Reads `directory` from query param or `x-opencode-directory` header (falls back to `process.cwd()`)
2. If no `workspace` query param: calls `Instance.provide({ directory, init: InstanceBootstrap, fn })` — the request runs inside a locally-scoped instance
3. If `workspace` param present and type is `"worktree"`: same as above but uses `workspace.directory`
4. If `workspace` is a remote workspace: checks `RULES` to decide whether to serve locally (e.g., `GET /session` returns cached data) or forward via the registered remote adaptor
5. Remote forwarding strips the `x-opencode-workspace` header and sends the request body as `arrayBuffer()` to preserve binary payloads

`RULES` currently hardcodes two exceptions:
- `GET /session` → always served locally (cached session list)
- `/session/status` → always forwarded to the remote

### `Instance.provide()` — Request Scoping

Every workspace-bound request runs inside `Instance.provide()`. This Effect context:
- Resolves the project root directory
- Initializes the `InstanceBootstrap` if the instance is new (loads config, sets up DB, wires providers)
- Makes `InstanceState` available to all downstream Effect calls within the request lifetime
- Ensures provider state, auth, and model lists are isolated to the project directory

### mDNS Service Discovery (`server/mdns.ts`)

When the server binds to a port, `MDNS.publish(port)` advertises it on the local network using `bonjour-service`. The service type is `http`, host is `opencode.local`, and the TXT record includes `path: "/"`. Errors during publish are caught and logged without crashing the server. `MDNS.unpublish()` tears down the Bonjour instance cleanly. This allows GUI clients and mobile apps on the same LAN to find the OpenCode server without static configuration.

### Response Projection (`server/projectors.ts`)

`initProjectors()` is called once at module load time (and again explicitly at the bottom of the file for safety). It wires `SyncEvent` with:
- `projectors` — the set of session projectors from `session/projectors.ts`
- `convertEvent` — a transform that intercepts `session.updated` events, reads the full `Session` row from the database, and replaces the minimal event payload with `{ sessionID, info: Session.fromRow(row) }` before the event is sent to subscribers

This ensures SSE clients always receive denormalized, ready-to-render session state rather than database delta records.

### Server Binding and Client Discovery

The server does not expose a fixed port. The port is determined at startup and published via mDNS. Local clients (TUI, CLI) can also discover the server via a socket file path derived from the global state directory. The `Flag.OPENCODE_SERVER_PASSWORD` / `Flag.OPENCODE_SERVER_USERNAME` flags enable optional HTTP Basic Auth for networked deployments.

## Runtime Behavior

1. `initProjectors()` runs at module import time, wiring the session projection layer before any request arrives.
2. `Server.Default` (lazy) constructs the `Hono` app on first access via `ControlPlaneRoutes()`.
3. Incoming requests traverse the middleware stack: error handler → optional basic auth → logging → CORS → optional compression.
4. Global routes (`/global/*`, `/auth/*`, `/doc`, `/log`) are resolved before the workspace middleware.
5. All other requests enter `WorkspaceRouterMiddleware`, which resolves the directory, scopes an `Instance`, and dispatches to `InstanceRoutes`.
6. Within `InstanceRoutes`, `hono-openapi` validators parse and type-check request bodies and params before handlers run.
7. Errors surface as `NamedError` JSON objects via `errorHandler`; the HTTP status code is derived from the error class.
8. SSE endpoints skip compression and hold the connection open, flushing events as they arrive from the `Bus`.
9. `MDNS.publish(port)` is called after the server successfully binds so LAN clients can discover it.

## Source Files

| File | Purpose |
|---|---|
| `packages/opencode/src/server/server.ts` | Main Hono app factory: middleware stack, auth, CORS, compression, OpenAPI, top-level routes |
| `packages/opencode/src/server/router.ts` | `WorkspaceRouterMiddleware`: directory resolution, `Instance.provide()` scoping, remote forwarding |
| `packages/opencode/src/server/middleware.ts` | `errorHandler`: structured error serialization to `NamedError` JSON |
| `packages/opencode/src/server/mdns.ts` | `MDNS`: mDNS/Bonjour LAN service discovery via `bonjour-service` |
| `packages/opencode/src/server/projectors.ts` | `initProjectors`: `SyncEvent` wiring for session event enrichment |
| `packages/opencode/src/server/routes/session.ts` | Session lifecycle endpoints |
| `packages/opencode/src/server/routes/provider.ts` | Provider and model listing endpoints |
| `packages/opencode/src/server/routes/file.ts` | File tree and content endpoints |
| `packages/opencode/src/server/routes/project.ts` | Project info and initialization endpoints |
| `packages/opencode/src/server/routes/config.ts` | Config read/write endpoints |
| `packages/opencode/src/server/routes/mcp.ts` | MCP registration and tool invocation endpoints |
| `packages/opencode/src/server/routes/pty.ts` | PTY session management endpoints |
| `packages/opencode/src/server/routes/event.ts` | SSE event bus endpoint |
| `packages/opencode/src/server/routes/workspace.ts` | Workspace management endpoints |
| `packages/opencode/src/server/routes/permission.ts` | Tool permission endpoints |
| `packages/opencode/src/server/routes/question.ts` | Interactive question/answer endpoints |
| `packages/opencode/src/server/routes/tui.ts` | TUI control endpoints |
| `packages/opencode/src/server/routes/global.ts` | Global event stream and sync-event endpoints |
| `packages/opencode/src/server/routes/experimental.ts` | Feature-flagged experimental endpoints |

## See Also

- [Control Plane and Workspaces](control-plane-and-workspaces.md)
- [MCP and ACP Integration](mcp-and-acp-integration.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Request to Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
