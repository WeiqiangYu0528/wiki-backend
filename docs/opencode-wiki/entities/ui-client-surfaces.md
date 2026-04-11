# UI Client Surfaces

## Overview

OpenCode exposes agent capabilities through multiple interactive surfaces that all share a single architectural principle: the server owns all state and the clients are renderers. The main `opencode` binary registers several commands that spin up or connect to an HTTP server built on Hono, then present a surface — terminal UI, browser tab, or headless — on top of that server's REST and SSE APIs.

The packages directly involved in local UI are `packages/opencode` (the CLI host), `packages/app` (the React/SolidJS web client bundled for the browser), `packages/ui` (shared component library), and `packages/web` (the documentation/marketing site built with Starlight). The first three together constitute what a user sees when they run `opencode` or `opencode web`. This page focuses on the runtime command layer and the shared formatting utilities; see [Server API](server-api.md) for the HTTP routes those commands expose and [Desktop and Remote Clients](desktop-and-remote-clients.md) for clients that run outside the local terminal.

## Key Types

| Symbol | File | Role |
|---|---|---|
| `ServeCommand` | `src/cli/cmd/serve.ts` | Yargs command: starts a headless Hono server, blocks indefinitely |
| `WebCommand` | `src/cli/cmd/web.ts` | Yargs command: starts the server and opens the web frontend in a browser |
| `AttachCommand` | `src/cli/cmd/tui/attach.ts` | Yargs command: connects the TUI to an already-running remote server |
| `TuiThreadCommand` | `src/cli/cmd/tui/thread.ts` | Default TUI command: starts the embedded server then launches the Ink/React TUI |
| `AcpCommand` | `src/cli/cmd/acp.ts` | Yargs command: starts the server and speaks the Agent Client Protocol over stdio |
| `UI` namespace | `src/cli/ui.ts` | Shared CLI formatting: `logo()`, `error()`, `println()`, `Style.*` constants |
| `Heap` namespace | `src/cli/heap.ts` | Memory watchdog: `Heap.start()` enables periodic heap-snapshot dumps |
| `NetworkOptions` | `src/cli/network.ts` | Shared yargs option group: `--port`, `--hostname`, `--mdns`, `--cors` |
| `resolveNetworkOptions` | `src/cli/network.ts` | Merges CLI flags with `Config.getGlobal()` to produce final bind parameters |
| `Server.listen` | `src/server/server.ts` | Creates and binds the Hono server, returns `{ hostname, port, url, stop }` |

## Architecture

### Command registration

All commands are registered in `src/index.ts` via Yargs. The CLI entry point performs three cross-cutting tasks before handing off to any command handler:

1. Reads `--print-logs` and `--log-level` to configure the structured logger.
2. Calls `Heap.start()` — a no-op unless `OPENCODE_AUTO_HEAP_SNAPSHOT` is set — which arms an interval that writes a V8 heap snapshot when RSS exceeds 2 GB.
3. Triggers a one-time SQLite migration from the legacy JSON storage format if the database file does not yet exist.

After that middleware, control flows to the matched command handler.

### Server start and network options

`ServeCommand`, `WebCommand`, and `TuiThreadCommand` all call `resolveNetworkOptions(args)` and then `Server.listen(opts)`. `resolveNetworkOptions` merges Yargs flags against the global config file so that persisted preferences (e.g. a fixed port or custom CORS origins) survive across invocations without flags. The resulting `{ hostname, port }` pair is what the server actually binds.

Binding on `0.0.0.0` enables network access for the web client: `WebCommand` then enumerates non-loopback, non-Docker IPv4 interfaces from `os.networkInterfaces()` and prints each one, giving the user a ready-to-paste LAN URL alongside the localhost URL.

mDNS advertisement is an optional overlay (`--mdns`, defaults to `opencode.local`). When enabled, `hostname` is automatically promoted from `127.0.0.1` to `0.0.0.0` so LAN peers can reach the service.

### ServeCommand — headless server

```
opencode serve [--port N] [--hostname H] [--mdns] [--cors ORIGIN...]
```

Starts the Hono server and blocks on a never-resolving Promise. No UI is rendered; all interaction happens through the HTTP API or SSE bus. If `OPENCODE_SERVER_PASSWORD` is not set, a warning is printed and the server runs unauthenticated. This mode is the intended entry point for remote-server deployments, CI pipelines, and any external client.

### WebCommand — browser client

```
opencode web [--port N] [--hostname H] [--mdns]
```

Starts the server, prints the `UI.logo()` wordmark plus access URLs, then calls `open(url)` (the npm package) to launch the default browser. The web frontend served at that URL is the built bundle from `packages/app`, statically embedded in the opencode binary. The browser client communicates with the server exclusively over HTTP: REST for commands and `GET /bus` (SSE) for event streaming.

### TuiThreadCommand — default interactive mode

```
opencode [--continue | --session ID] [--fork]
```

The default command (invoked when no subcommand is given). It spawns the embedded HTTP server in a background worker thread using Bun's Worker API (`worker.ts`). The TUI process communicates with that worker through an internal RPC bridge (`Rpc.client`) that wraps `fetch` calls and SSE events, keeping the Ink/React render loop isolated from network I/O. This is why the TUI works even on Windows without special socket support.

### AttachCommand — remote TUI

```
opencode attach <url> [--dir PATH] [--continue] [--session ID] [--fork] [--password PW]
```

Skips starting a local server entirely and connects the TUI directly to an existing server at `<url>`. Authentication is Basic Auth: the password comes from `--password` or `OPENCODE_SERVER_PASSWORD`, encoded as `Basic opencode:<password>` in `Authorization` headers. This is the primary mechanism for connecting a local terminal to a remote OpenCode server (e.g. one started on a cloud VM via `opencode serve`).

When `--dir` is supplied and the path does not exist locally (pure remote attach scenario), the directory string is forwarded to the server rather than `chdir`-ing locally.

### SSE subscription model

All clients subscribe to real-time events by holding an open HTTP connection to `/bus` (or `/global/event`). The server pushes typed event frames over that connection. The browser client, the TUI worker, and the Slack SDK all use this same mechanism; no client maintains its own event loop independent of the server.

### UI namespace — shared CLI formatting

`UI` in `src/cli/ui.ts` is a TypeScript namespace with no constructor or instantiation. All output goes to `process.stderr` so it does not contaminate stdout-piped workflows (e.g. shell scripting or ACP stdio mode). Key members:

- `UI.logo(pad?)` — renders the four-row braille wordmark. When both stdout and stderr are non-TTY it falls back to plain ASCII text; in a TTY it applies 256-colour block character shading.
- `UI.error(message)` — strips redundant `"Error: "` prefix and re-emits with red bold styling.
- `UI.println(...parts)` — writes parts joined by spaces plus a platform newline.
- `UI.empty()` — writes one blank line, deduplicating consecutive calls via a boolean flag.
- `UI.Style.*` — ANSI escape constants (highlight, dim, warning, danger, success, info, each with a bold variant).

## Runtime Behavior

The typical interactive startup sequence for `opencode` (TUI mode) is:

1. Yargs middleware: log initialisation, `Heap.start()`, optional DB migration.
2. `TuiThreadCommand.handler` resolves network options and calls `Server.listen` inside a Bun Worker.
3. The worker binds the Hono server on an OS-assigned port (default `--port 0`).
4. The main thread connects to the worker via `Rpc.client`, wrapping fetch and SSE into typed async calls.
5. The Ink/React TUI renders in the main thread, firing REST calls and receiving SSE events through the RPC bridge.
6. On exit, the Promise chain resolves, `server.stop()` is called, and the process exits.

For `opencode web`:

1. Same middleware as above.
2. `Server.listen` binds on the main thread (no separate worker).
3. `UI.logo()` and access URLs are printed to stderr.
4. `open(url)` launches the browser.
5. The main thread blocks indefinitely.

For `opencode serve`:

1. Same middleware.
2. `Server.listen` binds; hostname and port are printed to stdout.
3. Process blocks indefinitely; all interaction is over HTTP.

For `opencode attach <url>`:

1. Middleware runs but no server is started locally.
2. Auth headers are constructed from password flag or environment variable.
3. TUI connects directly to the remote URL.

## Source Files

| File | Purpose |
|---|---|
| `packages/opencode/src/index.ts` | CLI entry point; registers all commands, runs cross-cutting middleware |
| `packages/opencode/src/cli/cmd/serve.ts` | `ServeCommand`: headless server |
| `packages/opencode/src/cli/cmd/web.ts` | `WebCommand`: server + browser open |
| `packages/opencode/src/cli/cmd/tui/thread.ts` | `TuiThreadCommand`: embedded server + TUI |
| `packages/opencode/src/cli/cmd/tui/attach.ts` | `AttachCommand`: remote TUI attach |
| `packages/opencode/src/cli/cmd/tui/worker.ts` | Bun Worker: hosts server for TUI thread isolation |
| `packages/opencode/src/cli/cmd/tui/app.tsx` | Ink/React TUI root component |
| `packages/opencode/src/cli/ui.ts` | `UI` namespace: shared CLI formatting utilities |
| `packages/opencode/src/cli/heap.ts` | `Heap` namespace: memory watchdog and snapshot helper |
| `packages/opencode/src/cli/network.ts` | `NetworkOptions`, `resolveNetworkOptions` |
| `packages/opencode/src/server/server.ts` | `Server.listen`: Hono app factory and bind logic |
| `packages/app/package.json` | Web frontend (React/SolidJS) bundled and served by the server |
| `packages/ui/package.json` | Shared component library consumed by `packages/app` |
| `packages/web/package.json` | Documentation site (Astro/Starlight); separate from the app client |

## See Also

- [Desktop and Remote Clients](desktop-and-remote-clients.md)
- [Server API](server-api.md)
- [Client Server Agent Architecture](../concepts/client-server-agent-architecture.md)
- [Multi Client Product Architecture](../syntheses/multi-client-product-architecture.md)
- [Request To Session Execution Flow](../syntheses/request-to-session-execution-flow.md)
- [Architecture Overview](../summaries/architecture-overview.md)
- [Codebase Map](../summaries/codebase-map.md)
