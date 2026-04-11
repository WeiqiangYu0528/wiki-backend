# MCP and ACP Integration

## Overview

OpenCode integrates two distinct inter-process protocols: the Model Context Protocol (MCP) for connecting to external tool servers, and the Agent Client Protocol (ACP) for exposing OpenCode itself as an agent to IDE and editor extensions. MCP expands the available tool and resource surface by letting users configure connections to arbitrary MCP servers. ACP provides a standardized bridge that allows VS Code extensions, desktop clients, and other editors to embed OpenCode's agent capabilities without reimplementing the core logic.

Both systems are implemented in the `src/mcp/` and `src/acp/` directories respectively and interact with the same session, provider, and tool layers.

## Key Types

### MCP: `MCP.Resource`

Zod schema for a resource advertisement from an MCP server:

```
{ name, uri, description?, mimeType?, client }
```

The `client` field identifies which MCP server instance provided the resource, enabling the tool registry to route `read_resource` calls back to the correct connection.

### MCP: `MCP.Status`

A discriminated union (`connected | disabled | failed | needs_auth`) representing the current state of a named MCP server connection. The `failed` variant carries an `error` string. The `needs_auth` variant triggers the OAuth flow if the server requires it. Status values are exposed through the HTTP API so clients can display MCP server health.

### MCP: `MCP.ToolsChanged`

A `BusEvent` with schema `{ server: string }` published whenever the tool list of a connected MCP server changes. Consumers (the tool registry) subscribe to this event to invalidate their cached tool list and re-fetch.

### MCP: `MCP.BrowserOpenFailed`

A `BusEvent` with schema `{ mcpName, url }` published when the OAuth flow needs to open a browser but the `open` call fails. The TUI subscribes to this event (`TuiEvent`) to display a fallback URL to the user.

### MCP: `MCP.Failed`

A `NamedError` subtype carrying `{ name }` for structured error reporting when an MCP server connection cannot be established or maintained.

### ACP: `ACP` Namespace

The ACP namespace in `src/acp/agent.ts` implements the agent-side of the Agent Client Protocol. It imports from `@agentclientprotocol/sdk` the full set of ACP message types:

- `InitializeRequest` / `InitializeResponse` — capability negotiation on connection
- `NewSessionRequest`, `LoadSessionRequest`, `ResumeSessionRequest` / `ResumeSessionResponse` — session lifecycle
- `ForkSessionRequest` / `ForkSessionResponse` — branching a session from an existing one
- `PromptRequest` — submitting a new user message
- `CancelNotification` — interrupting a running agent turn
- `ListSessionsRequest` / `ListSessionsResponse` — retrieving available sessions
- `SetSessionModelRequest`, `SetSessionModeRequest`, `SetSessionConfigOptionRequest` — runtime configuration
- `AuthenticateRequest` — re-authentication mid-session
- `Usage`, `PlanEntry`, `ToolCallContent`, `ToolKind`, `Role`, `PermissionOption` — data types for streaming responses

## Architecture

### MCP Client Management

The MCP subsystem maintains a map of named server connections. Each entry in the user's MCP configuration (from `Config`) maps to a separate `Client` instance from `@modelcontextprotocol/sdk/client`. Three transport backends are supported:

- `StdioClientTransport` — for local subprocess MCP servers launched by OpenCode
- `SSEClientTransport` — for servers accessed over HTTP using Server-Sent Events
- `StreamableHTTPClientTransport` — for servers using the newer streamable HTTP transport

The MCP module uses `InstanceState` so that server connections are scoped to a workspace instance and re-established cleanly when an instance is recycled.

#### Tool Discovery

On connection, the MCP client calls the standard MCP `tools/list` RPC. Each returned `MCPToolDef` is converted to an AI SDK `Tool` using `dynamicTool()` and `jsonSchema()`. The tool's `execute` function wraps `client.callTool()` using `CallToolResultSchema` for response validation. A `ToolListChangedNotification` subscription ensures that if the server announces new or removed tools at runtime, `MCP.ToolsChanged` is published to trigger re-discovery.

#### OAuth Authentication

The MCP layer includes an OAuth flow for servers that require authentication. `McpOAuthProvider` implements the OAuth client and `McpOAuthCallback` handles the redirect URI. When a server returns an `UnauthorizedError`, the status transitions to `needs_auth`, `McpAuth` is invoked, and a browser window is opened via the `open` package. If the browser fails to open, `MCP.BrowserOpenFailed` is published so the TUI can display the URL inline.

### ACP Agent Bridge

The ACP agent bridge in `src/acp/agent.ts` exposes OpenCode's session and agent capabilities over the Agent Client Protocol. The `ACP` namespace connects the abstract protocol types from `@agentclientprotocol/sdk` to OpenCode's internal `AgentModule`, `Provider`, `Config`, and session management layers.

#### `ACPSessionManager`

`ACPSessionManager` (in `src/acp/session.ts`) maintains a mapping between ACP session IDs and OpenCode's internal session IDs. When an editor opens a session by ACP ID, the manager translates it to the storage-layer session ID for all subsequent operations.

#### Context Limit Integration

`getContextLimit(sdk, providerID, modelID, directory)` is called when an ACP client requests context information. It fetches the provider list from the OpenCode config API and resolves the context window size for the specific model, returning it to the ACP client so the editor can display token budget information.

#### Usage Updates

`sendUsageUpdate(connection, sdk, sessionID, directory)` reads the session messages from the SDK, finds the last assistant message, and pushes a `Usage` update back to the connected ACP client. This allows IDE panels to display live token consumption without polling.

### Tool Surface in the Registry

MCP tools are surfaced through the standard tool registry via the effect layer. When `MCP.ToolsChanged` is received, the tool layer re-queries each connected MCP server and merges the resulting tools into the registry under a namespaced key derived from the server name. This makes MCP tools indistinguishable from built-in tools from the AI model's perspective.

### ACP Protocol Flow

A typical ACP session from an editor proceeds:

1. Editor establishes an `AgentSideConnection` to OpenCode's ACP endpoint.
2. `InitializeRequest` is exchanged; OpenCode returns available providers, models, and session modes.
3. Editor sends `NewSessionRequest` or `LoadSessionRequest`.
4. Editor sends `PromptRequest` with the user message.
5. OpenCode runs the agent loop and streams `ToolCallContent` and assistant message parts back.
6. Editor can send `CancelNotification` to interrupt the turn.
7. `SetSessionModelRequest` and `SetSessionModeRequest` can be sent at any time to change the active model or mode.

## Runtime Behavior

### MCP Initialization

MCP servers are initialized lazily when a session starts. Each configured server entry is processed concurrently. Connection timeouts default to 30 seconds (`DEFAULT_TIMEOUT = 30_000`). If a server fails to connect, its status is set to `failed` and the error is stored but the session proceeds with the remaining servers.

The `ChildProcessSpawner` from `effect/unstable/process` combined with a `CrossSpawnSpawner` adapter is used for spawning stdio-based MCP server subprocesses. This ensures process lifecycle is managed within the Effect runtime.

### MCP Resources

Beyond tools, MCP servers can advertise `resources`. The `MCP.Resource` schema captures the resource advertisement. Resources are not automatically fetched but are made available through API endpoints for clients that wish to display or attach them.

### ACP Configuration

`ACPConfig` (from `src/acp/types.ts`) carries the ACP server binding options. The ACP server is typically activated by an editor extension that launches OpenCode with ACP flags rather than the standard TUI or headless server mode.

## Source Files

- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/mcp/index.ts` — `MCP` namespace, client management, tool discovery, OAuth flow, status tracking, bus events
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/mcp/oauth-provider.ts` — `McpOAuthProvider` OAuth client implementation
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/mcp/oauth-callback.ts` — `McpOAuthCallback` redirect handler
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/mcp/auth.ts` — `McpAuth` orchestration
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/acp/agent.ts` — `ACP` namespace, ACP-to-OpenCode bridge, session management, usage tracking
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/acp/session.ts` — `ACPSessionManager`
- `/Users/weiqiangyu/Downloads/wiki/opencode/packages/opencode/src/acp/types.ts` — `ACPConfig`

## See Also

- [Tool System](./tool-system.md) — MCP tools are merged into the tool registry
- [Provider System](./provider-system.md) — ACP exposes provider and model selection
- [Session System](./session-system.md) — ACP maps to internal session IDs
- [Server API](./server-api.md) — the HTTP server serves both MCP config endpoints and ACP connections
- [Plugin System](./plugin-system.md) — plugins can also add tools via the Hooks interface
