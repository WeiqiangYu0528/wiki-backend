# Canvas and Control UI

## Overview

Canvas and the Control UI are OpenClaw's visual surfaces. Together they provide an interactive workspace, a management dashboard, and a live-reload development environment for canvas applications. Both surfaces are served by the gateway rather than from a separate static server, which means UI asset delivery, Content Security Policy enforcement, and avatar serving all happen within the gateway's HTTP handling layer.

The canvas host (`src/canvas-host/server.ts`) serves user-authored canvas application files from a configured `rootDir`, provides WebSocket-based live reload for development, and handles A2UI requests — a secondary embedded UI path for agent-to-user interface components. The control UI (`src/gateway/control-ui.ts`) serves the React-based management frontend that communicates with the gateway via typed WebSocket frames. Asset delivery for the control UI includes CSP header computation, inline script hash injection, and support for a development override via the `OPENCLAW_CONTROL_UI_ROOT` environment variable.

Both surfaces are designed to be replaced or extended: the canvas host accepts a `watchFactory` and `webSocketServerClass` for injection in tests, and the control UI can have its asset root overridden at startup for hot-reload development workflows. The frontend communicates with the gateway exclusively via the typed WebSocket frame protocol — there is no REST API surface for UI-driven state changes.

## Key Types

### Canvas Host

| Type / Symbol | Location | Notes |
|---|---|---|
| `CanvasHostOpts` | `src/canvas-host/server.ts` | `{ runtime, rootDir?, port?, listenHost?, liveReload?, watchFactory?, webSocketServerClass? }` — full configuration for a canvas host instance |
| `CanvasHostServer` | `src/canvas-host/server.ts` | Return type: `{ port: number; rootDir: string; close(): Promise<void> }` |
| `CanvasHostHandler` | `src/canvas-host/server.ts` | Internal HTTP request handler; routes to static files or WebSocket upgrade |
| `CANVAS_HOST_PATH` | `src/canvas-host/server.ts` | `"/__openclaw__/canvas"` — URL prefix for canvas application assets |
| `CANVAS_WS_PATH` | `src/canvas-host/server.ts` | `"/__openclaw__/ws"` — WebSocket endpoint for live-reload notifications |

**Dependencies used by `CanvasHostServer`:**
- `chokidar` — filesystem watcher for detecting canvas file changes and triggering live reload
- `ws.WebSocketServer` — WebSocket server injected via `webSocketServerClass` option (allows test substitution)

### A2UI

| Type / Symbol | Location | Notes |
|---|---|---|
| `A2UI_PATH` | `src/canvas-host/a2ui.ts` | `"/__openclaw__/a2ui"` — URL prefix for A2UI assets |
| `handleA2uiHttpRequest()` | `src/canvas-host/a2ui.ts` | Serves A2UI static files; resolves the A2UI root via candidate path search (handles bun/dist/source layouts) |
| `injectCanvasLiveReload()` | `src/canvas-host/a2ui.ts` | Patches served HTML responses to inject the live-reload client script |

### Control UI

| Type / Symbol | Location | Notes |
|---|---|---|
| `handleControlUiRequest()` | `src/gateway/control-ui.ts` | Top-level HTTP request router for all Control UI asset requests |
| `ControlUiRootState` | `src/gateway/control-ui.ts` | `"bundled" \| "resolved" \| "invalid" \| "missing"` — tracks whether the asset root was found and is valid |
| `CONTROL_UI_BOOTSTRAP_CONFIG_PATH` | `src/gateway/control-ui.ts` | Path constant for the JSON config block injected into `index.html` at startup |
| `buildControlUiCspHeader()` | `src/gateway/control-ui.ts` | Computes the `Content-Security-Policy` header value for Control UI responses |
| `computeInlineScriptHashes()` | `src/gateway/control-ui.ts` | Hashes inline scripts in `index.html` so they can be listed in the CSP `script-src` directive |
| `CONTROL_UI_AVATAR_PREFIX` | `src/gateway/control-ui.ts` | URL prefix (`/avatar/...`) at which avatar images are served |
| `OPENCLAW_CONTROL_UI_ROOT` | environment | When set, overrides the resolved asset root; used for development hot reload without rebuilding |

## Architecture

### Canvas Host: File Serving and Live Reload

When `CanvasHostServer` starts, it binds an HTTP server to the configured `port` and `listenHost`. All requests under `CANVAS_HOST_PATH` (`/__openclaw__/canvas`) are resolved against `rootDir` and served as static files. Path resolution is handled by `src/canvas-host/file-resolver.ts`, which enforces that resolved paths stay within `rootDir` to prevent directory traversal.

If `liveReload` is enabled, `chokidar` watches `rootDir` for file changes. On any change, connected WebSocket clients on `CANVAS_WS_PATH` receive a reload notification. The `watchFactory` and `webSocketServerClass` options exist so tests can inject deterministic file watchers and mock WebSocket servers without touching the filesystem or network.

A2UI requests (`/__openclaw__/a2ui`) are handled by `handleA2uiHttpRequest()`, which locates the A2UI root directory by searching a list of candidate paths (covering bun package layouts, built dist directories, and source-level development layouts). For HTML responses, `injectCanvasLiveReload()` appends the live-reload client script before closing the `<body>` tag.

### Control UI: Gateway-Embedded Asset Server

The Control UI asset server is embedded directly in the gateway process. `handleControlUiRequest()` is registered as an HTTP handler on the gateway's main port; there is no separate static server process. At startup, the gateway resolves the asset root directory, which can be one of four states tracked by `ControlUiRootState`:

- `"bundled"` — assets were found at the default embedded path
- `"resolved"` — assets were found at a path provided via `OPENCLAW_CONTROL_UI_ROOT`
- `"invalid"` — a path was provided but does not contain the expected index file
- `"missing"` — no asset root could be found; the Control UI will return 503

The JSON bootstrap config (`CONTROL_UI_BOOTSTRAP_CONFIG_PATH`) is embedded into `index.html` before it is served. This allows the frontend to receive gateway-specific configuration (WebSocket URL, feature flags, version info) without a runtime API call at load time.

CSP enforcement is computed fresh at startup by `buildControlUiCspHeader()`. Inline scripts discovered by `computeInlineScriptHashes()` have their SHA-256 hashes listed in the `script-src` directive, satisfying strict CSP without requiring a nonce infrastructure.

Avatar images are served under `CONTROL_UI_AVATAR_PREFIX` (`/avatar/...`) directly by the gateway's control-UI handler, allowing the frontend to display user and agent avatars without cross-origin issues.

### Frontend Communication

The `ui/` directory contains the React-based Control UI application. It communicates with the gateway exclusively via a typed WebSocket frame protocol — not REST. This means all state changes (session management, config updates, channel interactions) are expressed as typed frames that the gateway dispatches to the appropriate internal subsystems. The frontend receives event frames over the same connection, enabling real-time reactive updates without polling.

## Runtime Behavior

### Canvas Host Startup

1. Caller invokes `CanvasHostServer` with `CanvasHostOpts`. `port` and `listenHost` default to loopback if not specified.
2. The HTTP server binds and starts accepting connections.
3. If `liveReload` is `true`, `chokidar` begins watching `rootDir`. A `ws.WebSocketServer` is created on `CANVAS_WS_PATH`.
4. Incoming HTTP requests under `CANVAS_HOST_PATH` are resolved via `file-resolver.ts` (path-traversal-safe) and served as static files with appropriate MIME types.
5. Requests under `A2UI_PATH` are handled by `handleA2uiHttpRequest()`, which resolves the A2UI root and serves files. HTML responses are patched by `injectCanvasLiveReload()` before being sent.
6. When `chokidar` detects a file change, all connected WebSocket clients on `CANVAS_WS_PATH` receive a reload message.
7. `CanvasHostServer.close()` shuts down the HTTP server, the WebSocket server, and the file watcher.

### Control UI Request Handling

1. An HTTP request arrives at the gateway on a path under the Control UI prefix.
2. `handleControlUiRequest()` checks `ControlUiRootState`. If `"missing"` or `"invalid"`, it returns 503.
3. For `index.html` requests, the gateway reads the file, injects the bootstrap config JSON block at `CONTROL_UI_BOOTSTRAP_CONFIG_PATH`, and adds the computed CSP header (including inline script hashes from `computeInlineScriptHashes()`).
4. For avatar requests matching `CONTROL_UI_AVATAR_PREFIX`, the avatar file is resolved and served directly.
5. All other asset requests are served from the resolved asset root with standard caching headers.
6. The frontend establishes a WebSocket connection to the gateway; subsequent interactions use the typed frame protocol rather than HTTP.

## Source Files

| File | Purpose |
|---|---|
| `src/canvas-host/server.ts` | `CanvasHostServer`, `CanvasHostOpts`, `CanvasHostHandler`; `CANVAS_HOST_PATH`, `CANVAS_WS_PATH`; `chokidar` and `ws` integration |
| `src/canvas-host/a2ui.ts` | `handleA2uiHttpRequest()`; `injectCanvasLiveReload()`; `A2UI_PATH`; candidate-path A2UI root resolution |
| `src/canvas-host/file-resolver.ts` | Path-traversal-safe static file resolution within a canvas root directory |
| `src/gateway/control-ui.ts` | `handleControlUiRequest()`; `ControlUiRootState`; `buildControlUiCspHeader()`; `computeInlineScriptHashes()`; `CONTROL_UI_BOOTSTRAP_CONFIG_PATH`; `CONTROL_UI_AVATAR_PREFIX` |
| `ui/` | React-based Control UI frontend application; communicates with the gateway via typed WebSocket frames |

## See Also

- [Node Host and Device Pairing](node-host-and-device-pairing.md)
- [Gateway Control Plane](gateway-control-plane.md)
- [Device Augmented Agent Architecture](../concepts/device-augmented-agent-architecture.md)
- [Canvas Voice and Device Control Loop](../syntheses/canvas-voice-and-device-control-loop.md)
