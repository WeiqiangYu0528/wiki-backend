# Multi Client Product Architecture

## Overview

This synthesis documents how TUI, web frontend, desktop app, and Slack all
connect to a single OpenCode core runtime. The core is started once — by
`ServeCommand` binding a Hono HTTP server on a local port — and every client
surface attaches to that server via HTTP REST and SSE. Session state, model
selection, permission rules, and Bus events are never duplicated per client:
they live in the core and clients only render what the Bus emits.

Understanding this architecture matters when diagnosing client-specific bugs. A
problem that looks like a TUI rendering issue may actually be a Bus subscription
gap. A feature that works on web but not on the desktop app may be due to a
difference in how the Electron shell proxies the HTTP server. Without knowing
which client connects through which channel, changes to the server API carry
hidden blast radius.

## Systems Involved

| System | Contribution |
| --- | --- |
| [CLI Runtime](../entities/cli-runtime.md) | `ServeCommand`, `AttachCommand`, `WebCommand` — the entry points that wire clients to the core |
| [Server API](../entities/server-api.md) | Hono HTTP server with REST routes and SSE endpoint; OpenAPI schema generation |
| [Bus System](../entities/storage-and-sync.md) | `Bus.publish` and SSE fanout that delivers events to every connected client |
| [UI Client Surfaces](../entities/ui-client-surfaces.md) | TUI (`AttachCommand`), web frontend (`WebCommand`), shared `app` package |
| [Desktop and Remote Clients](../entities/desktop-and-remote-clients.md) | Electron desktop shell, Tauri desktop shell, Slack integration |
| [Workspace Routing and Remote Control](workspace-routing-and-remote-control.md) | How remote workspaces integrate into the same client model |

## Step-by-Step Flow

### 1. `ServeCommand` Starts the Core

`ServeCommand` (registered in `index.ts`, implemented in `cli/cmd/serve.ts`):
1. Calls the project bootstrap helper to resolve the working directory.
2. Calls `Instance.provide({ directory })` to enter the ALS scope.
3. Calls the server factory (`server/server.ts`) to construct and start the Hono
   HTTP server.
4. Binds to a local TCP port (default or configured via `--port`).
5. Writes the bound port number to a well-known location on the filesystem
   (a `.opencode/port` file or equivalent) so other CLI processes can discover
   it without inter-process coordination.

### 2. Hono Server Registers REST Routes

The server constructor (`server/server.ts`) registers REST routes for all
subsystems:
- `GET /session`, `POST /session` — session list and creation
- `GET /session/:id`, `PATCH /session/:id` — session read and update
- `GET /message`, `POST /message` — message list and creation
- `GET /tool` — tool catalog
- `GET /permission`, `POST /permission/reply` — pending permissions and replies
- `GET /provider` — provider and model list
- `GET /workspace` — workspace records

The server also generates and serves an OpenAPI schema at `/openapi.json` so
SDK clients and code-generation tools can discover the full API surface.
Each route handler reads `InstanceContext` from ALS to scope DB queries to the
current project.

### 3. Hono Server Mounts the SSE Endpoint

The server mounts `GET /events` as a long-lived SSE endpoint:
- When a client connects, a subscriber callback is registered with `Bus.subscribe`.
- The Hono response uses chunked transfer encoding (no `Content-Length`).
- Each `Bus.publish` call causes the subscriber to write a serialized frame:
  `data: {"type":"...", "payload":{...}}\n\n`
- The SSE format is standard (compatible with browser `EventSource` API).
- Event types emitted: `session.updated`, `message.updated`, `permission.asked`,
  `permission.replied`, `server.instance.disposed`.

### 4. TUI Attaches via `AttachCommand`

`AttachCommand` (in `cli/cmd/tui/attach.ts`):
1. Reads the port from the well-known port discovery file written by `ServeCommand`.
2. If the file is absent or the port is unreachable (`ECONNREFUSED`), exits with a
   user-facing "server not running" error.
3. Opens an HTTP connection to `http://localhost:{port}`.
4. Subscribes to `GET /events` using a streaming fetch or `EventSource`-compatible
   client library.
5. Renders the TUI using the `ink` React renderer (or equivalent), updating
   terminal output as `session.updated` and `message.updated` SSE frames arrive.

`TuiThreadCommand` provides an alternative thread-focused view over the same
SSE connection, subscribing to the same `GET /events` endpoint.

### 5. Web Frontend Served by `WebCommand`

`WebCommand` (in `cli/cmd/web.ts`):
1. Starts a static file server that serves pre-built `app` package assets
   (HTML, JS, CSS bundles from `packages/app/dist/`).
2. Opens the user's default browser pointing at `http://localhost:{port}`.
3. The web frontend is a React SPA using:
   - Browser `fetch` API for REST calls to the core's Hono server
   - Browser `EventSource` API for the SSE event stream on `GET /events`
4. No separate backend process is required. The same Hono server that serves the
   REST API also delivers SSE — `WebCommand` only serves the static shell assets.

### 6. Desktop Electron App

The Electron shell (in `packages/desktop-electron`):
1. On startup, spawns a `ServeCommand` child process, or locates a running one
   via the port discovery file.
2. Opens a `BrowserWindow` that loads `http://localhost:{port}` — the same URL
   the web frontend uses.
3. The embedded web view communicates with the Hono server over HTTP and SSE
   exactly as the browser-based web frontend does.
4. There is no Electron-specific backend or IPC for data calls; all data flows
   through the Hono server's standard REST and SSE endpoints.

The **Tauri variant** (`packages/desktop`) follows the same pattern but uses
Tauri's Rust runtime as the native shell. Tauri's `invoke` bridge handles any
OS-level calls (file picker, notifications); all AI/session data flows through
Hono.

### 7. SDK Programmatic Access

The OpenCode SDK is generated from the Hono OpenAPI schema at `/openapi.json`.
SDK clients:
- Call REST endpoints to create sessions, post messages, and list tools.
- Subscribe to `GET /events` to receive the SSE stream, parsing `BusEvent`
  frames with the same Zod schema used by the TUI and web frontend.
- Require the server to already be running (started by `ServeCommand`); they do
  not spawn their own server.
- Can be used in CI pipelines, test harnesses, or external integrations without
  a UI client.

### 8. Slack Integration

The Slack client registers event handlers for incoming Slack messages via the
Slack Bolt SDK:
1. When a Slack message arrives, the handler constructs a session prompt.
2. The handler posts the prompt to the core's REST API
   (`POST /session/{id}/message`), just as the TUI or web frontend would.
3. Responses are streamed back via SSE subscription, then forwarded to the Slack
   thread as reply messages.
4. The Slack surface does not own any session state — it is a thin HTTP+SSE
   client over the same core API.

### 9. Bus Pub/Sub Fanout

Every significant state change in the core calls `Bus.publish(event, payload)`:
- New text chunk streamed from model → `message.updated`
- Tool call made → `message.updated` (with new `ToolCallPart`)
- Permission request raised → `permission.asked`
- Permission request resolved → `permission.replied`
- Session title updated → `session.updated`
- Compaction started → `session.updated` (with `time.compacting` set)

The SSE endpoint's `Bus.subscribe` callback iterates all open connections and
writes the serialized event frame to each. All clients receive identical event
streams. Per-session filtering is done client-side by checking
`payload.sessionID` on each received event frame.

### 10. Permission Events Reach All Clients

When `Permission.Event.Asked` fires, all clients receive the SSE frame:
```
{ "type": "permission.asked", "payload": { "id": "...", "sessionID": "...",
  "permission": "bash", "patterns": ["..."], "always": [], "metadata": {...},
  "tool": { "messageID": "...", "callID": "..." } } }
```

The first client to POST `Permission.ReplyInput` to `POST /permission/reply`
(`{ requestID, reply: "once" | "always" | "reject", message?: string }`)
unblocks tool execution for all clients. The `permission.replied` SSE frame is
then broadcast so all clients can dismiss their pending permission UI.

### 11. Session and Message Events Keep Clients in Sync

`session.updated` SSE frames carry the full updated `Session.Info` object:
- `time.updated`, `time.compacting`, `summary`, `revert`, `permission` fields.

`message.updated` SSE frames carry the full `MessageV2.WithParts` with all
accumulated parts.

Clients that reconnect after a brief disconnection:
1. Re-fetch current state via `GET /session/{id}` and `GET /message?sessionID={id}`.
2. Resume SSE subscription from the current state.
3. Do not need to replay the full event log.

### 12. Teardown

When `ServeCommand` receives SIGINT or exits cleanly:
1. `Instance.disposeAll()` iterates all `InstanceContext` entries in the cache.
2. `State.dispose(directory)` is called for each, triggering all registered
   `Entry.dispose` callbacks.
3. `server.instance.disposed` is emitted on `GlobalBus` for each directory.
4. The Hono server closes all open SSE connections by ending the streaming
   responses.
5. Clients detect the closed SSE stream (`EventSource` fires an `error` event
   or the fetch stream reader returns `done: true`) and surface a reconnection UI.

## Data at Each Boundary

| Boundary | Data Crossing | Key Types / Format |
| --- | --- | --- |
| `ServeCommand` → Hono server | Startup config | Port number, project directory, `Config` object |
| `ServeCommand` → filesystem | Port discovery | Plain text at `.opencode/port` — decimal port string |
| TUI → Hono REST | Session/message operations | HTTP GET/POST; `Session.Info`, `MessageV2.WithParts` JSON |
| TUI → Hono SSE | Event stream | `GET /events` long-lived connection; SSE frames |
| Web frontend → Hono REST | Session/message operations | Browser `fetch`; JSON request/response |
| Web frontend → Hono SSE | Event stream | Browser `EventSource` on `GET /events` |
| Electron shell → Web frontend | Embedded web view | `BrowserWindow` loading `http://localhost:{port}` |
| SDK client → Hono REST | Programmatic session control | Generated SDK methods; JSON bodies |
| Slack handler → Hono REST | Message posting | HTTP POST to `POST /session/{id}/message` |
| Hono SSE → all clients | Bus event frames | `data: {"type":"...","payload":{...}}\n\n` — standard SSE |
| Bus → SSE subscribers | Typed event payloads | `session.updated` (`Session.Info`), `message.updated` (`MessageV2.WithParts`), `permission.asked` (`Permission.Request`), `permission.replied`, `server.instance.disposed` |
| Client → Hono REST (permission) | User decision | `POST /permission/reply` with `Permission.ReplyInput { requestID, reply, message? }` |

## Failure Points

| Stage | What Can Fail | Mechanism | Observable Symptom |
| --- | --- | --- | --- |
| `ServeCommand` port bind | Port already in use by another process | `EADDRINUSE` from Node `net.listen` | Server fails to start; all clients see `ECONNREFUSED` |
| Port discovery | Port file not written (server crashed before writing) | `fs.readFile` returns `ENOENT` | `AttachCommand` shows "server not running" error |
| Port discovery | Port file is stale (server restarted on different port) | Client connects to wrong port; `ECONNREFUSED` | TUI cannot attach; user must manually find server |
| SSE subscription | Client connects before `ServeCommand` finishes boot | SSE stream opens but no events until first `Bus.publish` | Client appears connected; must fetch REST for initial state |
| SSE subscription | Client disconnects before first event written | `Bus.subscribe` callback writes to closed socket | Write throws; subscriber silently dropped from registry |
| SSE stream | Network interruption mid-session | TCP RST or FIN while events in flight | Client stops receiving updates; `EventSource` fires `error` |
| SSE fanout | One slow subscriber blocks the iteration loop | Synchronous `for...of` with blocking write | All other clients experience delayed events |
| Web frontend static server | Build assets missing (`npm run build` not run) | Static server returns 404 for `index.html` | Browser shows blank page or 404 |
| Electron shell spawn | `ServeCommand` not found or crashes at startup | Child process exits with non-zero code | Desktop app shows "connecting..." indefinitely |
| Slack handler | Slack API rate limit or OAuth token expiry | Slack API returns 429 or 401 | Slack messages not delivered; silent failure in core |
| Permission reply race | Two clients POST replies simultaneously | Second `POST /permission/reply` after `Deferred` resolved | Second reply errors; no functional harm but stale UI on second client |
| Server not running | Client tries to connect with no `ServeCommand` | `ECONNREFUSED` from `fetch` or `EventSource` | All clients show connection error; user must run `opencode serve` |

## Source Evidence

| File | Function / Symbol | Why It Matters |
| --- | --- | --- |
| `packages/opencode/src/index.ts` | `ServeCommand`, `AttachCommand`, `WebCommand`, `TuiThreadCommand` registrations | Root command registry; all client entry points |
| `packages/opencode/src/cli/cmd/serve.ts` | `ServeCommand.handler` | Starts Hono server; writes port discovery file |
| `packages/opencode/src/cli/cmd/tui/attach.ts` | `AttachCommand.handler` | Reads port file; opens SSE connection; drives TUI render loop |
| `packages/opencode/src/cli/cmd/web.ts` | `WebCommand.handler` | Serves `app` static assets; opens browser |
| `packages/opencode/src/server/server.ts` | Hono server factory, route registration, SSE endpoint | Central HTTP server; REST and `GET /events` SSE surface |
| `packages/opencode/src/bus/index.ts` | `Bus.publish`, `Bus.subscribe` | SSE fanout; subscriber callback registration |
| `packages/app/package.json` | `build` script, entry point | Web frontend package; SPA shell for browser and Electron clients |
| `packages/desktop-electron/package.json` | `main` entry, Electron build config | Electron shell packaging; `BrowserWindow` construction |

## See Also

- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [UI Client Surfaces](../entities/ui-client-surfaces.md)
- [Desktop and Remote Clients](../entities/desktop-and-remote-clients.md)
- [Server API](../entities/server-api.md)
- [Workspace Routing and Remote Control](workspace-routing-and-remote-control.md)
- [Request to Session Execution Flow](request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
