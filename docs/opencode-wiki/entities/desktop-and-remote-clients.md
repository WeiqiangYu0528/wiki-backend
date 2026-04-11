# Desktop and Remote Clients

## Overview

OpenCode's server-owns-state architecture makes it straightforward to graft additional client shells on top of the same HTTP/SSE API. Beyond the built-in terminal UI and browser surfaces, the monorepo ships four external client categories: two native desktop wrappers (Tauri and Electron), a Slack bot integration, and a JavaScript SDK that underpins all of them. A Zed editor extension and the `opencode acp` command round out the editor-integration story.

None of these clients embed their own agent loop. Each one discovers a running OpenCode server (or spawns one as a sidecar), then drives it through the same REST API and SSE event bus that the TUI and web clients use. The design principle is the same as for local surfaces: the server is the single source of truth; clients are renderers or bridges.

## Key Types

| Symbol | Package / File | Role |
|---|---|---|
| `spawnLocalServer` | `desktop-electron/src/main/server.ts` | Spawns the `opencode serve` CLI as a child process sidecar; polls health endpoint until ready |
| `getDefaultServerUrl` / `setDefaultServerUrl` | `desktop-electron/src/main/server.ts` | Persists a remote server URL in Electron's store so the user can reconnect across restarts |
| `AcpCommand` | `opencode/src/cli/cmd/acp.ts` | Starts an embedded server, then bridges Agent Client Protocol messages between stdin/stdout and the REST API |
| `AgentSideConnection` | `@agentclientprotocol/sdk` | ACP library type: wraps an ndjson stream into a structured agent session |
| `createOpencode` | `sdk/js/src/index.ts` | Convenience factory: starts an embedded server and returns a typed client bound to it |
| `createOpencodeClient` | `sdk/js/src/client.ts` | Typed HTTP client (generated from OpenAPI); adds directory-header injection and disables fetch timeout |
| `createOpencodeServer` | `sdk/js/src/server.ts` | SDK-level server spawner; accepts `{ port }` and returns `{ url }` |
| Slack `App` | `slack/src/index.ts` | Bolt framework instance; handles `app_mention` and `message` events, one OpenCode session per thread |

## Architecture

### Tauri desktop app (`packages/desktop`)

The Tauri package wraps the `packages/app` web frontend in a native window using the Tauri v2 framework (Rust backend + WebKit webview). The Rust layer (`src-tauri/src/`) manages OS-specific concerns: display backend selection on Linux (X11 vs Wayland via `linux_windowing.rs`), window chrome customisation, and markdown rendering. The web frontend loads the same bundle served by the HTTP server; for development, Vite runs on `http://localhost:1420`.

The Tauri shell does not start or stop the OpenCode server itself — that responsibility belongs to the Electron shell or to the user running `opencode serve` separately. The Tauri binary is the primary distribution artifact for macOS and Linux native app bundles.

Build command: `bun run --cwd packages/desktop tauri build`
Dev command: `bun run --cwd packages/desktop tauri dev`

### Electron desktop app (`packages/desktop-electron`)

The Electron shell is more feature-complete than the Tauri variant as a standalone product: it manages the full lifecycle of the OpenCode server as a sidecar process. Key responsibilities handled in `src/main/`:

- **Server lifecycle** (`server.ts`): `spawnLocalServer(hostname, port, password)` invokes the `opencode serve` CLI binary as a child process with `CommandChild` (a thin wrapper over Electron's `utilityProcess` or spawn). It then polls `GET /health` every 100 ms until the process responds or exits. The resolved URL is stored with `setDefaultServerUrl` so the renderer can reconnect after a crash.
- **Remote server support**: `getDefaultServerUrl` / `setDefaultServerUrl` persist a URL in Electron's persistent key-value store. Users can point the app at a remote server (e.g. a cloud VM) without changing code; the renderer simply fetches from that URL.
- **Auto-update** (`index.ts`): `electron-updater` watches for new releases (`autoUpdater`) and can apply them in the background.
- **IPC** (`ipc.ts`): Contextual bridges (preload → main) expose `sendDeepLinks`, `sendMenuCommand`, and `sendSqliteMigrationProgress` to the renderer process.
- **WSL support**: The `WslConfig` store entry enables a mode where the sidecar is launched inside WSL2 rather than directly on Windows, allowing the server to access Linux file paths.

The Electron app supports three channels (`dev`, `beta`, `prod`) distinguished by `APP_IDS` and `APP_NAMES` constants; channel selection is baked in at build time.

### ACP command — editor agent protocol (`packages/opencode`)

```
opencode acp [--port N] [--cwd PATH]
```

`AcpCommand` implements the Agent Client Protocol (ACP), a structured ndjson-over-stdio protocol used by editors to communicate with an agent. The handler:

1. Sets `process.env.OPENCODE_CLIENT = "acp"` to signal the server that this is an editor-driven session.
2. Starts an embedded OpenCode server with `Server.listen`.
3. Creates a typed SDK client pointed at the local server.
4. Wraps `process.stdin` and `process.stdout` into Web Streams.
5. Passes those streams to `ndJsonStream` and hands the result to `AgentSideConnection`, which drives the ACP session lifecycle.

The Zed extension (`packages/extensions/zed/extension.toml`) is the primary consumer of this command. Its `extension.toml` declares an `[agent_servers.opencode]` section that downloads the correct platform binary and invokes it with `args = ["acp"]`. The extension works on macOS ARM/x86, Linux ARM/x86, and Windows x86.

Other editors can integrate via the same pattern: spawn `opencode acp`, communicate via ndjson on stdio.

### Slack integration (`packages/slack`)

The Slack package is a standalone bot process, not embedded in the main binary. It uses Bolt's Socket Mode (WebSocket to Slack's infrastructure, avoiding a public inbound webhook).

Architecture:

1. A single `createOpencode({ port: 0 })` call (from `@opencode-ai/sdk`) starts an embedded server and returns a bound client.
2. A global SSE listener subscribes to `event.subscribe()` and forwards `message.part.updated` events (specifically completed tool calls) as threaded Slack messages.
3. On each incoming Slack message or mention, the bot looks up or creates a `sessions` map entry keyed by `channel + thread_ts`. Each thread gets its own OpenCode session ID, so conversations are isolated.
4. Tool execution updates are echoed back to the thread as `*toolName* - title` messages.

Required environment variables: `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN`.
Required OAuth scopes: `chat:write`, `app_mentions:read`, `channels:history`, `groups:history`.

### JavaScript SDK (`packages/sdk/js`)

The SDK package (`@opencode-ai/sdk`) is the programmatic interface for all external consumers — the Slack bot, the Electron shell's renderer, the ACP command, and third-party integrations.

Key exports:

- `createOpencodeClient(config?)` — builds a fully typed HTTP client from the generated OpenAPI spec (`gen/`). It injects an `x-opencode-directory` header so a single server can serve multiple working directories, and it disables fetch timeouts (important for long-running agent calls).
- `createOpencodeServer(options?)` — spawns an embedded server and returns its URL. Accepts `{ port: 0 }` to bind on an OS-assigned port.
- `createOpencode(options?)` — convenience combinator: calls both of the above and returns `{ client, server }`.

The `v2/` subdirectory contains a newer generation of types and client code that the TUI and ACP commands import directly. The `gen/` directory contains machine-generated types from `openapi.json` at the SDK root.

### Enterprise package (`packages/enterprise`)

The `enterprise` package is a SolidStart application (SolidJS SSR framework). Based on its source layout (`src/routes/`, `src/core/`), it provides a hosted control-plane UI — likely the web dashboard for team or enterprise accounts. It is a separate deployment target from the embedded web client in `packages/app` and does not run locally as part of the standard `opencode` binary.

## Runtime Behavior

### How each client discovers the server

| Client | Discovery mechanism |
|---|---|
| TUI (local) | Server URL comes from the in-process worker RPC bridge; no external lookup needed |
| TUI (remote attach) | User supplies URL explicitly: `opencode attach http://host:port` |
| Electron app | `getDefaultServerUrl()` reads persisted store; falls back to spawning a local sidecar via `spawnLocalServer` |
| Tauri app | Expects server to be reachable at a known URL; does not manage server lifecycle |
| Slack bot | `createOpencode({ port: 0 })` binds locally; all sessions share one server instance |
| SDK consumers | Caller provides `baseUrl` to `createOpencodeClient`, or calls `createOpencode` for a self-contained setup |
| Zed extension | Spawns `opencode acp`; no URL negotiation needed — communication is over stdio |

### Authentication

The server optionally requires HTTP Basic Auth. The username is `opencode` (or the value of `OPENCODE_SERVER_USERNAME`); the password is `OPENCODE_SERVER_PASSWORD`. Clients pass the credential as `Authorization: Basic <base64>`. The Electron app passes the password when spawning the sidecar (`spawnLocalServer(hostname, port, password)`) and the `AttachCommand` does the same when connecting remotely. Requests without credentials are accepted when no password is configured, but the server prints a warning.

### Remote workspace scenario

A typical remote-server workflow:

1. Run `opencode serve --hostname 0.0.0.0 --port 4096` on the remote machine. Set `OPENCODE_SERVER_PASSWORD` to a strong secret.
2. From a local terminal: `opencode attach http://<remote-ip>:4096 --password <secret> --dir /path/on/remote`.
3. The local TUI renders as normal; all agent execution happens on the remote machine.

The Electron desktop app supports the same flow: set the stored server URL to the remote address and the renderer will connect without spawning a local sidecar.

## Source Files

| File | Purpose |
|---|---|
| `packages/opencode/src/cli/cmd/acp.ts` | `AcpCommand`: ACP stdio bridge |
| `packages/opencode/src/cli/cmd/tui/attach.ts` | `AttachCommand`: remote TUI attach |
| `packages/desktop/src-tauri/src/` | Rust backend for the Tauri native app |
| `packages/desktop/package.json` | Tauri desktop build configuration |
| `packages/desktop-electron/src/main/index.ts` | Electron main process entry point |
| `packages/desktop-electron/src/main/server.ts` | Sidecar spawn, health polling, URL persistence |
| `packages/desktop-electron/src/main/ipc.ts` | Preload-to-main IPC handler registration |
| `packages/slack/src/index.ts` | Slack bot: Bolt app setup, session map, SSE relay |
| `packages/slack/README.md` | Slack app credentials and setup instructions |
| `packages/sdk/js/src/index.ts` | `createOpencode`, `createOpencodeClient`, `createOpencodeServer` |
| `packages/sdk/js/src/client.ts` | Typed HTTP client with directory header injection |
| `packages/sdk/js/openapi.json` | OpenAPI spec that drives SDK type generation |
| `packages/extensions/zed/extension.toml` | Zed extension manifest: downloads binary, invokes `opencode acp` |
| `packages/enterprise/src/` | SolidStart enterprise dashboard application |

## See Also

- [UI Client Surfaces](ui-client-surfaces.md)
- [Control Plane and Workspaces](control-plane-and-workspaces.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Multi Client Product Architecture](../syntheses/multi-client-product-architecture.md)
- [Request To Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
