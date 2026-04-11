# MCP Integration Architecture

## Overview

This synthesis describes how the Model Context Protocol (MCP) integrates with Claude Code across all layers: server configuration in settings, connection management at startup and runtime, tool discovery and merging with built-in tools, agent-specific MCP servers, channel-based permission relaying, and OAuth authentication flows. MCP is a cross-cutting concern that touches configuration, tool assembly, permission checking, and the agent system.

## Systems Involved

- [MCP System](../entities/mcp-system.md) -- client connections, tool/resource/prompt discovery
- [Configuration System](../entities/configuration-system.md) -- MCP server definitions in settings files
- [Tool System](../entities/tool-system.md) -- MCP tools as `Tool` instances, merged into the tool pool
- [Permission System](../entities/permission-system.md) -- MCP tool permissions and channel-based permission relay
- [Agent System](../entities/agent-system.md) -- agent-specific MCP server initialization
- [Skill System](../entities/skill-system.md) -- MCP-sourced skills/prompts

## Interaction Model

### Configuration Layer

MCP server definitions come from multiple configuration sources, each with a scope:

```
+-------------------+     +-------------------+     +-------------------+
| Global Settings   |     | Project Settings  |     | Enterprise/Managed|
| ~/.claude/        |     | .claude/          |     | Managed MCP JSON  |
| settings.json     |     | settings.json     |     |                   |
+--------+----------+     +--------+----------+     +--------+----------+
         |                         |                          |
         +------------+------------+--------------------------+
                      |
              +-------v--------+
              | getMcpServers()|
              | (config.ts)   |
              | Merges all     |
              | sources with   |
              | scope tags     |
              +-------+--------+
                      |
                      v
              Scoped server configs:
              { name, command|url, scope, ... }
```

Each server config is tagged with its `ConfigScope` (`global`, `project`, `policySettings`, `plugin`, etc.). The `getMcpServers()` function in `src/services/mcp/config.ts` merges configs from:

- Global settings (`~/.claude/settings.json` -> `mcpServers`)
- Project settings (`.claude/settings.json` -> `mcpServers`)
- Local project settings (`.claude/settings.local.json`)
- Enterprise/managed settings (`managed-mcp.json`)
- Plugin-provided MCP servers (`getPluginMcpServers()`)
- Claude.ai cloud MCP configs (`fetchClaudeAIMcpConfigsIfEligible()`)
- Dynamic configs (passed at runtime by SDK callers)

Server configs support three transport types:
- **Stdio**: `{ command, args, env }` -- spawns a subprocess
- **SSE/HTTP**: `{ url }` -- connects via Server-Sent Events or Streamable HTTP
- **WebSocket**: `{ url }` -- connects via WebSocket

Environment variables in configs are expanded via `expandEnvVarsInString()`.

### Connection Management

```
getMcpServers()
  |
  v
+------------------------+
| MCPConnectionManager   |  (React component, REPL context)
| useManageMCPConnections|
+----------+-------------+
           |
           v
+----------+-----------+
| connectToServer()    |  (memoized per server name)
| (client.ts)         |
| - Create transport   |
| - Initialize client  |
| - Discover tools     |
| - Discover prompts   |
| - Discover resources |
+----------+-----------+
           |
           v
+----------+-----------+
| AppState.mcp         |
| { clients, tools,    |
|   commands, resources}|
+----------------------+
```

`MCPConnectionManager` (`MCPConnectionManager.tsx`) is a React context provider that wraps `useManageMCPConnections()`. This hook:

1. Reads MCP config (including dynamic config from SDK callers)
2. Connects to each server via `connectToServer()` (memoized)
3. Fetches tools, prompts, and resources from each connected server
4. Updates `AppState.mcp` with clients, tools, commands, and resources
5. Handles reconnection and enable/disable toggling

`connectToServer()` in `client.ts` creates the appropriate transport (Stdio, SSE, HTTP, or WebSocket), initializes the MCP `Client`, negotiates capabilities, and discovers available tools/prompts/resources. Connection is memoized so reconnecting to the same server reuses the existing client.

### Tool Discovery and Merging

MCP tools are wrapped as standard `Tool` objects via the `MCPTool()` factory:

```
MCP Server
  |
  v
fetchToolsForClient()        -- calls client.listTools()
  |
  v
MCPTool(serverName, mcpTool) -- wraps each MCP tool as a Tool
  |
  v
AppState.mcp.tools           -- stored in app state
  |
  v
useMergedTools()             -- REPL hook
  or
assembleToolPool()           -- shared pure function
  |
  v
Final tool pool for query()
```

**`MCPTool`** (`src/tools/MCPTool/MCPTool.ts`): Factory that creates a `Tool` from an MCP tool definition. The resulting tool:
- Has name `mcp__{serverName}__{toolName}` (normalized for API compatibility)
- Delegates `call()` to `client.callTool()` on the MCP connection
- Sets `isMcp: true` and stores `mcpInfo: { serverName, toolName }`
- Handles MCP-specific features: structured content, resource links, image content, elicitation
- Respects `alwaysLoad` / `shouldDefer` metadata for ToolSearch optimization

**`useMergedTools()`** (`src/hooks/useMergedTools.ts`): React hook that combines built-in tools with MCP tools:

```typescript
function useMergedTools(initialTools, mcpTools, toolPermissionContext): Tools {
  const assembled = assembleToolPool(toolPermissionContext, mcpTools)
  return mergeAndFilterTools(initialTools, assembled, toolPermissionContext.mode)
}
```

**`assembleToolPool()`** (`src/tools.ts`): Pure function used by both REPL and `runAgent()`:
1. Calls `getAllBaseTools()` for the built-in tool list
2. Filters out tools denied by `alwaysDenyRules`
3. Deduplicates (MCP tools with same name as built-ins are excluded)
4. Applies feature gates and CLI-exclusion rules

### Agent-Specific MCP Servers

Agent definitions (in `.claude/agents/*.md` frontmatter) can declare `mcpServers`:

```yaml
---
mcpServers:
  - existing-server-name           # reference by name
  - name: inline-server            # inline definition
    command: node
    args: [server.js]
---
```

`initializeAgentMcpServers()` in `src/tools/AgentTool/runAgent.ts`:

1. Checks if the agent definition has `mcpServers`
2. For string references, looks up existing configs via `getMcpConfigByName()`
3. For inline definitions, connects to new servers
4. Merges agent-specific clients with parent clients
5. Fetches tools from agent-specific servers
6. Returns a cleanup function that disconnects newly-created clients when the agent finishes

Agent MCP tools are additive -- the agent sees its parent's tools plus its own MCP tools. When `strictPluginOnlyCustomization` locks MCP to plugin-only, user-controlled agents skip frontmatter MCP servers, but plugin/built-in agents are allowed.

### MCP Skills and Prompts

MCP servers can expose prompts (via `listPrompts()`), which are surfaced as skills:

```
MCP Server
  |-- listPrompts()
  v
Command objects with:
  type: 'prompt'
  loadedFrom: 'mcp'
  name: 'mcp__{server}__{prompt}'
  |
  v
AppState.mcp.commands
  |
  v
SkillTool.getAllCommands()  -- merges local + MCP skills
```

MCP prompts marked as skills (via metadata) appear in the skill discovery system. `SkillTool.getAllCommands()` merges local/bundled skills with MCP skills, deduplicating by name. MCP skill builders (`mcpSkillBuilders.ts`) handle the conversion.

### Channel Permission Relay

MCP servers that declare `capabilities.experimental['claude/channel/permission']` can participate in permission approval:

```
Permission prompt triggered
  |
  +---> Local UI (terminal)
  |
  +---> Channel servers (Telegram, Discord, etc.)
          |
          v
        Server sends prompt to user via channel
          |
          v
        User replies "yes <code>" or "no <code>"
          |
          v
        Server parses reply, emits:
          notifications/claude/channel/permission
          { request_id, behavior: 'allow'|'deny' }
          |
          v
        channelPermissions.resolve(requestId, behavior)
          |
          v
        First resolver wins (race with local UI)
```

The system generates a 5-character confirmation code per request. Channel servers parse the user's reply and emit structured events -- Claude Code never interprets free-text channel messages as approvals. See `channelPermissions.ts` for the reply format spec and code generation.

### OAuth Authentication

MCP servers using HTTP/SSE transport may require OAuth authentication. The flow is handled by `src/services/mcp/auth.ts`:

1. **Discovery**: `discoverAuthorizationServerMetadata()` and `discoverOAuthServerInfo()` probe the server for OAuth endpoints.
2. **Client registration**: Dynamic client registration with the authorization server.
3. **Authorization**: Opens a browser for the user to authenticate, with a local HTTP server capturing the redirect.
4. **Token management**: Tokens are stored in secure storage (macOS Keychain, etc.) and refreshed automatically.
5. **Cross-App Access (XAA)**: Enterprise environments may use IDP token exchange for cross-application SSO via `performCrossAppAccess()`.

The `McpAuthTool` tool is created dynamically when an MCP server requires authentication, allowing the model to trigger the OAuth flow.

### MCP Resources

MCP servers can expose resources (files, data) via `listResources()`:

- **`ListMcpResourcesTool`**: Lists available resources from all connected MCP servers
- **`ReadMcpResourceTool`**: Reads a specific resource by URI
- Resources are stored in `AppState.mcp.resources` keyed by server name

## Key Interfaces

### MCPServerConnection (`src/services/mcp/types.ts`)

```typescript
type MCPServerConnection = {
  type: 'connected' | 'pending' | 'error'
  name: string
  client: Client              // MCP SDK client
  config: ScopedMcpServerConfig
  tools: Tool[]
  commands: Command[]
  resources?: ServerResource[]
}
```

### ScopedMcpServerConfig (`src/services/mcp/types.ts`)

```typescript
type ScopedMcpServerConfig = McpServerConfig & {
  scope: ConfigScope  // 'global' | 'project' | 'policySettings' | ...
}

type McpServerConfig =
  | McpStdioServerConfig     // { command, args, env }
  | McpSSEServerConfig       // { url, headers }
  | McpHTTPServerConfig      // { url, headers }
  | McpWebSocketServerConfig // { url }
```

### assembleToolPool() (`src/tools.ts`)

```typescript
function assembleToolPool(
  toolPermissionContext: ToolPermissionContext,
  mcpTools: Tools,
): Tools
```

### useMergedTools() (`src/hooks/useMergedTools.ts`)

```typescript
function useMergedTools(
  initialTools: Tools,
  mcpTools: Tools,
  toolPermissionContext: ToolPermissionContext,
): Tools
```

### initializeAgentMcpServers() (`src/tools/AgentTool/runAgent.ts`)

```typescript
function initializeAgentMcpServers(
  agentDefinition: AgentDefinition,
  parentClients: MCPServerConnection[],
): Promise<{
  clients: MCPServerConnection[]
  tools: Tools
  cleanup: () => Promise<void>
}>
```

## See Also

- [MCP System](../entities/mcp-system.md) -- detailed entity documentation for the MCP subsystem
- [Tool System](../entities/tool-system.md) -- how MCP tools integrate as standard `Tool` objects
- [Configuration System](../entities/configuration-system.md) -- settings files where MCP servers are defined
- [Permission System](../entities/permission-system.md) -- MCP tool permission rules and deny-rule filtering
- [Agent System](../entities/agent-system.md) -- agent-specific MCP server lifecycle
- [Skill System](../entities/skill-system.md) -- MCP prompts as discoverable skills
- [Agent-Tool-Skill Triad](./agent-tool-skill-triad.md) -- how agent MCP servers compose with tool filtering
- [Permission Enforcement Pipeline](./permission-enforcement-pipeline.md) -- channel permission relay details
