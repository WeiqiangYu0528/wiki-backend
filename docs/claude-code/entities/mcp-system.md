# MCP System

## Overview

Model Context Protocol (MCP) integration allows Claude Code to connect to external tool servers. MCP servers provide additional tools, resources, and capabilities beyond the built-in set. The system handles server connections, tool discovery, OAuth authentication, and agent-specific MCP configurations.

The core entry points are `connectToServer()` (memoized per server name), `fetchToolsForClient()` (LRU-memoized), and `getMcpToolsCommandsAndResources()` which orchestrates the full startup flow: load configs, connect in batches (local servers at lower concurrency, remote servers at higher concurrency), discover tools/commands/resources, and merge them with built-in tools. Configuration comes from multiple scopes -- local `.mcp.json`, user/global settings, project settings, enterprise managed config, dynamic plugin-provided servers, and Claude.ai proxy servers.

## Key Types

### MCPServerConnection (discriminated union)

Defined in `services/mcp/types.ts`. Represents the current state of a server:

| Variant | `type` | Key Fields | Description |
|---|---|---|---|
| `ConnectedMCPServer` | `'connected'` | `client`, `capabilities`, `serverInfo`, `instructions`, `cleanup` | Active connection with MCP SDK `Client` instance |
| `FailedMCPServer` | `'failed'` | `error?` | Connection attempt failed |
| `NeedsAuthMCPServer` | `'needs-auth'` | -- | OAuth or authentication required before connecting |
| `PendingMCPServer` | `'pending'` | `reconnectAttempt?`, `maxReconnectAttempts?` | Connection in progress or awaiting retry |
| `DisabledMCPServer` | `'disabled'` | -- | Explicitly disabled by user |

All variants carry `name: string` and `config: ScopedMcpServerConfig`.

### Server Configuration

`McpServerConfig` is a Zod-validated discriminated union of transport-specific schemas:

| Schema | `type` | Purpose |
|---|---|---|
| `McpStdioServerConfigSchema` | `'stdio'` (or omitted) | Local subprocess via stdin/stdout |
| `McpSSEServerConfigSchema` | `'sse'` | Remote server via Server-Sent Events |
| `McpSSEIDEServerConfigSchema` | `'sse-ide'` | IDE extension (internal only) |
| `McpWebSocketIDEServerConfigSchema` | `'ws-ide'` | IDE extension via WebSocket (internal only) |
| `McpHTTPServerConfigSchema` | `'http'` | Remote server via Streamable HTTP |
| `McpWebSocketServerConfigSchema` | `'ws'` | Remote server via WebSocket |
| `McpSdkServerConfigSchema` | `'sdk'` | In-process SDK MCP server |
| `McpClaudeAIProxyServerConfigSchema` | `'claudeai-proxy'` | Claude.ai proxy server |

`ScopedMcpServerConfig` extends any config variant with `scope: ConfigScope` (`'local'` | `'user'` | `'project'` | `'dynamic'` | `'enterprise'` | `'claudeai'` | `'managed'`) and optional `pluginSource` for plugin-provided servers.

### Transport Layers

- **InProcessTransport** (`InProcessTransport.ts`): Linked pair of transports for running MCP server and client in the same process. `createLinkedTransportPair()` returns `[clientTransport, serverTransport]`; `send()` on one side delivers to `onmessage` on the other via `queueMicrotask`.
- **SdkControlClientTransport / SdkControlServerTransport** (`SdkControlTransport.ts`): Bridge between CLI process (MCP client) and SDK process (MCP server) through structured control messages over stdout/stdin. Supports multiple simultaneous SDK MCP servers routed by `server_name`.

### MCPTool

Defined in `tools/MCPTool/MCPTool.ts`. A thin wrapper built via `buildTool()` with `isMcp: true`. Most fields are overridden at runtime in `client.ts` when wrapping discovered MCP tools:

- `name` -- replaced with `mcp__serverName__toolName` (or bare tool name in SDK no-prefix mode)
- `description`, `prompt` -- set from the MCP server's tool description (truncated at `MAX_MCP_DESCRIPTION_LENGTH`)
- `call()` -- replaced with logic that calls the MCP server via `client.request()`, handles progress events, session retry, and result transformation
- `inputJSONSchema` -- passed through directly from the MCP server's tool schema
- `checkPermissions()` -- returns `'passthrough'` with suggestions for local settings rules
- `mcpInfo` -- carries unnormalized `{ serverName, toolName }` for permission checking

### MCPCliState

Serialized snapshot of MCP state for CLI communication:

```typescript
interface MCPCliState {
  clients: SerializedClient[]
  configs: Record<string, ScopedMcpServerConfig>
  tools: SerializedTool[]
  resources: Record<string, ServerResource[]>
  normalizedNames?: Record<string, string>
}
```

## Server Lifecycle

1. **Configuration loading** -- `getAllMcpConfigs()` in `config.ts` merges servers from all scopes: project `.mcp.json`, user global config, enterprise managed config, Claude.ai proxy configs, dynamic/plugin servers. Each server gets a `ConfigScope` tag. Disabled servers are filtered out early. Enterprise policy (`shouldAllowManagedMcpServersOnly()`) can restrict to managed-only.

2. **Connection** -- `connectToServer()` is `memoize`-d (lodash) by server name + config. It creates the appropriate transport (StdioClientTransport, SSEClientTransport, StreamableHTTPClientTransport, WebSocketTransport, InProcessTransport, or SdkControlClientTransport), instantiates an MCP SDK `Client`, calls `client.connect()`, and returns a `ConnectedMCPServer` or error/auth variant. For servers requiring OAuth, it returns `NeedsAuthMCPServer` and creates an `McpAuthTool` instead.

3. **Tool discovery** -- `fetchToolsForClient()` is LRU-memoized. For connected servers with `capabilities.tools`, it calls `tools/list`, sanitizes Unicode, and maps each MCP tool to a `Tool` object by spreading `MCPTool` and overriding name, description, call, schema, and behavioral flags (from MCP tool annotations: `readOnlyHint`, `destructiveHint`, `openWorldHint`).

4. **Tool merging with built-in tools** -- Tools are deduplicated by name. MCP tools that collide with built-in names use the `mcp__` prefix to avoid shadowing (unless `CLAUDE_AGENT_SDK_MCP_NO_PREFIX` is set for SDK servers). Resource tools (`ListMcpResourcesTool`, `ReadMcpResourceTool`) are added once if any server supports resources.

5. **Batched connection** -- `getMcpToolsCommandsAndResources()` partitions servers into local (stdio/sdk, lower concurrency via `getMcpServerConnectionBatchSize()`) and remote (higher concurrency via `getRemoteMcpServerConnectionBatchSize()`), then runs both groups in parallel via `processBatched()`.

6. **Cleanup** -- `ConnectedMCPServer` carries a `cleanup()` async function. The `connectToServer` cache can be cleared via `clearServerCache()` for reconnection. `registerCleanup()` is used for session-level teardown.

## Tool Name Normalization

Tool names follow the format `mcp__<normalizedServerName>__<normalizedToolName>`:

- `normalizeNameForMCP()` (`normalization.ts`) replaces any character not matching `[a-zA-Z0-9_-]` with underscores. For Claude.ai servers (names starting with `"claude.ai "`), it also collapses consecutive underscores and strips leading/trailing underscores to avoid interference with the `__` delimiter.
- `buildMcpToolName()` (`mcpStringUtils.ts`) combines the normalized server and tool names with the `mcp__` prefix.
- `mcpInfoFromString()` parses the fully qualified name back into `{ serverName, toolName }`. Known limitation: server names containing `__` will parse incorrectly.
- The `mcpInfo` field on each tool carries the original unnormalized names for accurate permission checking via `getToolNameForPermissionCheck()`.
- Deferred loading: when tool count is high, MCP tools with a `searchHint` (from `_meta['anthropic/searchHint']`) are eligible for deferred loading via ToolSearch. Tools with `_meta['anthropic/alwaysLoad']` bypass deferral.

## Agent MCP Integration

Agent definitions can declare MCP servers in their frontmatter via the `mcpServers` field (`AgentMcpServerSpec[]`):

- **Referenced servers** (string entries) -- refer to servers already present in global config. These use the shared memoized `connectToServer()` and persist across agent invocations.
- **Inline servers** (object entries as `{ [name]: config }`) -- agent-specific server definitions. Extracted by `extractAgentMcpServers()` in `utils.ts`, which groups by server name and tracks which agents reference each server. These are cleaned up on agent exit.
- Plugin restriction and admin-trust boundaries: `filterMcpServersByPolicy()` in `config.ts` enforces enterprise policies. Plugin-provided servers carry `pluginSource` for channel gate checks. `isRestrictedToPluginOnly()` can restrict tool availability.

## OAuth and Authentication

OAuth support is configured per-server via the `oauth` field on SSE and HTTP server configs:

```typescript
oauth?: {
  clientId?: string
  callbackPort?: number
  authServerMetadataUrl?: string   // Must use https://
  xaa?: boolean                    // Cross-App Access (XAA / SEP-990)
}
```

- When a server returns a 401, the system creates an `McpAuthTool` that the user can invoke to complete the OAuth flow.
- `auth.ts` (largest file at ~89KB) handles OAuth discovery, token storage, refresh, and the full authorization code flow.
- `isMcpAuthCached()` tracks recently-failed auth servers (15-minute TTL) to avoid repeated probe round-trips.
- `hasMcpDiscoveryButNoToken()` further closes the gap: servers that have been probed but hold no token are skipped until the user runs `/mcp`.
- **Cross-App Access (XAA)**: per-server boolean flag (`xaa.ts`, `xaaIdpLogin.ts`). IdP connection details come from `settings.xaaIdp` -- configured once, shared across all XAA-enabled servers.
- **Channel permissions** (`channelPermissions.ts`): when running over channels (Telegram, iMessage, Discord), permission prompts are relayed via MCP channel servers. The server must declare `capabilities.experimental['claude/channel/permission']`. Gated by GrowthBook flag `tengu_harbor_permissions`.
- **Channel allowlist** (`channelAllowlist.ts`): controls which MCP servers are allowed as channel providers.

## Source Files

| File | Description |
|---|---|
| `services/mcp/types.ts` | Zod schemas for all server config variants, `MCPServerConnection` union, `MCPCliState` |
| `services/mcp/client.ts` | Core connection logic: `connectToServer()`, `fetchToolsForClient()`, `getMcpToolsCommandsAndResources()`, tool call execution, result transformation |
| `services/mcp/config.ts` | Config loading/merging from all scopes, add/remove server, enterprise policy enforcement |
| `services/mcp/normalization.ts` | `normalizeNameForMCP()` -- character replacement for API-compatible names |
| `services/mcp/mcpStringUtils.ts` | `buildMcpToolName()`, `mcpInfoFromString()`, `getMcpPrefix()`, display name extraction |
| `services/mcp/InProcessTransport.ts` | Linked transport pair for in-process MCP server/client communication |
| `services/mcp/SdkControlTransport.ts` | CLI-to-SDK bridge transport via control messages over stdout/stdin |
| `services/mcp/auth.ts` | OAuth discovery, token management, authorization code flow, refresh logic |
| `services/mcp/xaa.ts` | Cross-App Access (XAA / SEP-990) implementation |
| `services/mcp/xaaIdpLogin.ts` | XAA IdP login flow |
| `services/mcp/channelPermissions.ts` | Permission relay over channel MCP servers |
| `services/mcp/channelAllowlist.ts` | Channel server allowlist enforcement |
| `services/mcp/channelNotification.ts` | Channel notification handling |
| `services/mcp/claudeai.ts` | Claude.ai proxy server config fetching |
| `services/mcp/elicitationHandler.ts` | MCP elicitation request handling |
| `services/mcp/envExpansion.ts` | Environment variable expansion in server configs |
| `services/mcp/headersHelper.ts` | Dynamic header generation for HTTP/SSE/WS servers |
| `services/mcp/oauthPort.ts` | OAuth callback port management |
| `services/mcp/officialRegistry.ts` | Official MCP server registry integration |
| `services/mcp/utils.ts` | Type guards, `extractAgentMcpServers()`, project server status |
| `services/mcp/useManageMCPConnections.ts` | React hook managing MCP connection lifecycle in the UI |
| `services/mcp/vscodeSdkMcp.ts` | VS Code SDK MCP integration |
| `services/mcp/MCPConnectionManager.tsx` | React component for MCP connection management UI |
| `tools/MCPTool/MCPTool.ts` | Base `MCPTool` definition -- thin wrapper overridden per-tool at runtime |
| `tools/MCPTool/prompt.ts` | Default description and prompt text for MCP tools |
| `tools/MCPTool/UI.ts` | Render functions for MCP tool use/result messages |

## See Also

- [Tool System](tool-system.md)
- [Agent System](agent-system.md)
- [Plugin System](plugin-system.md)
- [MCP Integration Architecture](../syntheses/mcp-integration-architecture.md)
