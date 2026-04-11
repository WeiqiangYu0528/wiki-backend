# MCP Service

## Overview

The MCP Service manages connections to external Model Context Protocol (MCP) servers that extend Claude Code with additional tools, commands, and resources. It handles the full lifecycle of server connections: parsing configuration, establishing transport-specific connections (stdio, SSE, HTTP, WebSocket, SDK), tracking connection state, and exposing the connected server's capabilities as usable tools. The service also handles OAuth authentication for servers that require it, name normalization to avoid conflicts, and runtime reconnection and toggling.

## Key Types / Key Concepts

The core discriminated union tracks server state:

```typescript
type MCPServerConnection =
  | ConnectedMCPServer    // successfully connected
  | FailedMCPServer       // connection attempt failed
  | NeedsAuthMCPServer    // requires OAuth before connecting
  | PendingMCPServer      // connection in progress
  | DisabledMCPServer     // user-disabled

type ConnectedMCPServer = {
  client: Client           // MCP SDK Client instance
  name: string
  type: 'connected'
  capabilities: ServerCapabilities
  serverInfo?: { name: string; version: string }
  instructions?: string
  config: ScopedMcpServerConfig
  cleanup: () => Promise<void>
}
```

Transport variants are validated at parse time using Zod schemas:

```typescript
type Transport = 'stdio' | 'sse' | 'sse-ide' | 'http' | 'ws' | 'sdk'

// Example config for a local process server
type McpStdioServerConfig = {
  type?: 'stdio'
  command: string
  args: string[]
  env?: Record<string, string>
}
```

`ScopedMcpServerConfig` extends any server config with a `scope` field indicating its origin: `local | user | project | dynamic | enterprise | claudeai | managed`.

## Architecture

The MCP service is organized into three layers:

**Configuration layer** (`types.ts`, `config.ts`, `normalization.ts`):
Defines all server config schemas using Zod, normalizes server names to avoid tool name collisions, and builds the merged config map from multiple scope sources.

**Connection layer** (`client.ts`, `useManageMCPConnections.ts`, `MCPConnectionManager.tsx`):
The `useManageMCPConnections` React hook manages the live set of server connections. It exposes `reconnectMcpServer(name)` to re-establish a dropped connection and `toggleMcpServer(name)` to enable/disable a server at runtime. The `MCPConnectionManager` React context provider wraps these functions and makes them available to child components via `useMcpReconnect()` and `useMcpToggleEnabled()`.

**Transport layer** (`InProcessTransport.ts`, `SdkControlTransport.ts`):
Specialized transports for in-process servers (running inside the same Node/Bun process) and SDK-controlled servers (managed by the embedding SDK).

**Auth layer** (`auth.ts`, `oauthPort.ts`, `xaa.ts`, `xaaIdpLogin.ts`):
OAuth flows for MCP servers that require authentication. Supports standard OAuth and Cross-App Access (XAA / SEP-990) for enterprise identity provider integration.

**Channel layer** (`channelAllowlist.ts`, `channelPermissions.ts`, `channelNotification.ts`):
For plugin-provided servers, enforces a channel allowlist gate so only authorized plugins can contribute MCP servers.

**CLI state** (`types.ts` — `MCPCliState`):
Serializable snapshot of all connections, configs, tools, and resources, used by the `/mcp` CLI command to display status.

## Source Files

| File | Purpose |
|------|---------|
| `services/mcp/types.ts` | All config schemas (Zod) and connection state types |
| `services/mcp/MCPConnectionManager.tsx` | React context provider for reconnect/toggle |
| `services/mcp/useManageMCPConnections.ts` | Core connection lifecycle hook |
| `services/mcp/client.ts` | Low-level connection establishment |
| `services/mcp/config.ts` | Config loading and merging from multiple scopes |
| `services/mcp/normalization.ts` | Tool name normalization to prevent conflicts |
| `services/mcp/auth.ts` | OAuth authentication for MCP servers |
| `services/mcp/InProcessTransport.ts` | In-process transport implementation |
| `services/mcp/SdkControlTransport.ts` | SDK-controlled transport |
| `services/mcp/channelAllowlist.ts` | Plugin channel allowlist gate |
| `services/mcp/utils.ts` | Shared MCP utilities (e.g., `isMcpTool()`) |
| `services/mcp/officialRegistry.ts` | Official MCP server registry integration |

## See Also

- [API Service](api-service.md) — MCP tool schemas are serialized into API requests
- [OAuth Service](oauth-service.md) — MCP servers may require OAuth; shares auth infrastructure
- [Analytics Service](analytics-service.md) — MCP connection events are logged
- [Async Event Queue](../concepts/async-event-queue.md) — connection state changes are async
- [Request Lifecycle](../syntheses/request-lifecycle.md) — MCP tools are dispatched during tool execution
