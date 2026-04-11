# LSP and Code Intelligence

## Overview

OpenCode integrates the Language Server Protocol (LSP) to provide code intelligence capabilities that go beyond text manipulation. Rather than relying solely on the AI model's knowledge of code structure, the LSP subsystem launches and manages language server processes for the workspace, collects real-time diagnostics, and exposes go-to-definition, hover, document symbols, and workspace symbol queries as structured data. These capabilities enrich the context available to the AI agent when it is reading, navigating, or modifying source files.

The LSP subsystem lives in `src/lsp/` and is organized under the `LSP` namespace. It is built on `vscode-jsonrpc` for protocol framing and integrates with the application `Bus` for event propagation.

## Key Types

### `LSP.Range`

A Zod schema for a text range in a document:

```
{ start: { line, character }, end: { line, character } }
```

Ranges are used throughout LSP responses (diagnostics, symbol locations, definition results) and are exposed through the server HTTP API under the `Range` ref.

### `LSP.Symbol`

Workspace-level symbol type with `name`, `kind` (integer LSP symbol kind), and a `location` carrying a `uri` and `Range`. Used for workspace-wide symbol search results.

### `LSP.DocumentSymbol`

File-level symbol type adding `detail` and `selectionRange` in addition to the fields from `LSP.Symbol`. Used for outline/structure queries on a specific open file.

### `LSP.Status`

A Zod schema tracking the health of a managed language server:

```
{ id, name, root, status: "connected" | "error" }
```

Status objects are published via `LSP.Event.Updated` so clients can display which language servers are active and whether they are healthy.

### `LSP.Event.Updated`

A `BusEvent` with an empty payload published whenever the set of managed language servers changes — on connection, disconnection, or status transition. Consumers such as the TUI subscribe to this event to refresh the LSP status display.

### `LSPClient.Diagnostic`

Re-exported from `vscode-languageserver-types`, this is the standard LSP diagnostic type. Diagnostics are stored per file path in a `Map<string, Diagnostic[]>` inside each `LSPClient` instance.

### `LSPClient.InitializeError`

A `NamedError` carrying `{ serverID }` thrown when an LSP server fails to complete its initialization handshake.

### `LSPClient.Event.Diagnostics`

A `BusEvent` with schema `{ serverID, path }` published after the `textDocument/publishDiagnostics` notification is received and stored. Subscribers can query the specific diagnostic list for the affected file path.

## Architecture

### Module Structure

The `src/lsp/` directory contains five files with distinct responsibilities:

| File | Responsibility |
|---|---|
| `index.ts` | `LSP` namespace, `LSP.Service`, instance state, server management layer |
| `client.ts` | `LSPClient` — jsonrpc connection wrapper, diagnostic storage, LSP request methods |
| `server.ts` | `LSPServer` — configuration schema for language server entries |
| `launch.ts` | `spawn()` — subprocess creation with piped stdio |
| `language.ts` | `LANGUAGE_EXTENSIONS` — map from file extension to language ID |

### `LSPServer` Configuration

Each entry in the LSP configuration (from `Config`) describes a language server to manage. `LSPServer.Handle` is the runtime representation of a running server process, including the child process reference and any server-specific `initialization` options to return for `workspace/configuration` requests.

### `LSPClient.create()`

`LSPClient.create({ serverID, server, root })` establishes the JSON-RPC connection over the server process's stdio streams using `createMessageConnection` from `vscode-jsonrpc/node`. A `StreamMessageReader` wraps `process.stdout` and a `StreamMessageWriter` wraps `process.stdin`.

The client immediately registers handlers for key protocol notifications and requests:

- `textDocument/publishDiagnostics` — stores diagnostics in the `Map` and publishes `LSPClient.Event.Diagnostics` (debounced by `DIAGNOSTICS_DEBOUNCE_MS = 150` ms). For the TypeScript server, initial diagnostics on files that have never been seen before are suppressed to reduce noise.
- `window/workDoneProgress/create` — acknowledged with `null` (progress notifications are not used by OpenCode).
- `workspace/configuration` — returns the server's `initialization` options so the language server can receive its startup configuration without an explicit `initialize` options field.
- `client/registerCapability` and `client/unregisterCapability` — no-op handlers to satisfy servers that send capability registration requests.
- `workspace/workspaceFolders` — returns a single folder entry pointing to `root` as a file URI.

### Language Server Spawn Flow

`launch.ts` exports a `spawn(cmd, args?, opts?)` function that wraps `Process.spawn()` with explicit `stdin: "pipe"`, `stdout: "pipe"`, `stderr: "pipe"` options. This produces a `Child` process with all three streams available as non-null handles, which is required for the jsonrpc message framing.

The main `LSP` namespace (in `index.ts`) imports `spawn` as `lspspawn` and uses it to start language server processes defined in the project configuration. The `Flag.OPENCODE_PURE` flag suppresses LSP initialization in pure mode.

### Language Extension Map

`LANGUAGE_EXTENSIONS` in `language.ts` maps file extensions (e.g., `.ts`, `.py`, `.go`) to their LSP language identifier strings. This map is used when opening documents (`textDocument/didOpen`) to populate the `languageId` field required by the protocol.

### `SymbolKind` Enum

The `index.ts` file defines a `SymbolKind` enum matching the LSP specification integer values. This is used when constructing `LSP.Symbol` and `LSP.DocumentSymbol` results for API responses, enabling clients to display appropriate icons for each symbol type.

## Runtime Behavior

### Server Initialization Sequence

1. `LSP.layer` initializes via `InstanceState.make()`, scoping language server connections to the current workspace instance.
2. For each entry in the `Config` LSP configuration, a subprocess is spawned via `lspspawn`.
3. `LSPClient.create()` is called to wrap the subprocess in a jsonrpc connection.
4. The `initialize` request is sent to the language server with the workspace root URI and client capabilities.
5. `initialized` notification is sent after the server responds.
6. `LSP.Event.Updated` is published with the new status.

### Diagnostic Flow

1. Language server sends `textDocument/publishDiagnostics` after analyzing a file.
2. `LSPClient` normalizes the URI to a filesystem path using `Filesystem.normalizePath(fileURLToPath(uri))`.
3. The diagnostic list is stored in the `Map<string, Diagnostic[]>` keyed by the normalized path.
4. `LSPClient.Event.Diagnostics` is published with `{ serverID, path }`.
5. Consumers (the agent tool layer) can query the stored diagnostic list on demand.

### LSP-Backed Tool Operations

The LSP service provides methods that the tool layer calls to enrich AI operations:

- `textDocument/definition` — resolves a symbol at a given position to its definition location
- `textDocument/hover` — retrieves type and documentation information for a symbol
- `textDocument/documentSymbol` — returns the symbol outline of a file
- `workspace/symbol` — searches for symbols matching a query across the workspace
- `textDocument/references` — finds all references to a symbol

These methods use `withTimeout` to avoid blocking the agent loop if a language server is slow to respond.

### Connection Lifecycle

Language server processes are managed as children of the OpenCode process. If a language server exits unexpectedly, the error is captured and the server's status transitions to `"error"`. The `LSP.Event.Updated` event is published so the TUI can display the failure. Reconnection is not automatic; users must restart the session or trigger re-initialization.

## Source Files

- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/lsp/index.ts` — `LSP` namespace, service layer, event definitions, `Symbol`, `DocumentSymbol`, `Status`, `Range` types
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/lsp/client.ts` — `LSPClient.create()`, diagnostic storage, jsonrpc connection, `InitializeError`, `Event.Diagnostics`
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/lsp/server.ts` — `LSPServer` configuration schema and `Handle` type
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/lsp/launch.ts` — `spawn()` subprocess helper
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/lsp/language.ts` — `LANGUAGE_EXTENSIONS` mapping

## See Also

- [Tool System](./tool-system.md) — LSP-backed tools (definition, hover, symbols) are registered in the tool registry
- [Session System](./session-system.md) — diagnostic events can be attached to session context
- [Project and Instance System](./project-and-instance-system.md) — `InstanceState` scopes LSP connections to workspace instances
- [Server API](./server-api.md) — LSP status and diagnostic endpoints are exposed via HTTP
