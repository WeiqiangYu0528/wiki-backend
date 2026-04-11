# MCP and ACP Bridges

## Overview

OpenClaw exposes two outward-facing protocol bridges that allow external clients to drive the assistant runtime without bypassing gateway authority. The **MCP bridge** wraps OpenClaw channels as a Model Context Protocol server, making them discoverable and callable from MCP-aware hosts such as Claude Desktop. The **ACP bridge** adapts gateway-backed sessions for Agent Client Protocol clients — editors, IDE extensions, and scripted automation — presenting a standards-compliant agent surface over the same underlying session machinery.

Both bridges are thin translation layers, not independent runtimes. Each one connects to the gateway via `GatewayClient` and forwards requests through the existing channel and session infrastructure. Neither bridge owns session state, policy, or model configuration; it acquires those from the gateway on every interaction. This design means that any permission or configuration change made through the gateway's control plane is immediately visible to MCP and ACP callers without a bridge restart.

The two bridges differ in their transport, protocol contract, and client audience. The MCP bridge uses `StdioServerTransport` — it is spawned as a subprocess by MCP hosts — while the ACP bridge runs as a persistent server process with its own HTTP or socket endpoint. Session keys in the ACP subsystem are namespaced as `acp:...` to avoid collision with interactive and cron sessions. Understanding both bridges requires reading them together with the Channel System and Session System pages, because the bridges only route; they do not execute.

## Key Types

### MCP Bridge

| Type / Symbol | Location | Purpose |
|---|---|---|
| `createOpenClawChannelMcpServer(opts)` | `src/mcp/channel-server.ts` | Factory that constructs a `McpServer` instance backed by an `OpenClawChannelBridge` |
| `OpenClawChannelBridge` | `src/mcp/channel-bridge.ts` | Connects to the gateway via `GatewayClient`; translates MCP tool calls into channel invocations |
| `registerChannelMcpTools(server, bridge)` | `src/mcp/channel-tools.ts` | Populates the MCP tool catalog from the set of registered channels |
| `ClaudePermissionRequestSchema` | `src/mcp/channel-server.ts` | Notification handler that bridges Claude Desktop permission prompts back through the gateway |
| `StdioServerTransport` | `@modelcontextprotocol/sdk/server/stdio.js` | Standard I/O transport used by the MCP server (process-level, spawned by host) |
| MCP loopback HTTP server | `src/gateway/mcp-http.ts` | Internal HTTP server started by the gateway so the agent runtime can call MCP tools without an external host |

```typescript
// Conceptual shape of the MCP server factory
createOpenClawChannelMcpServer(opts: {
  gatewayHost: string;
  gatewayPort: number;
  gatewayTls?: boolean;
  // ... auth opts
}): Promise<{ server: McpServer; transport: StdioServerTransport }>
```

### ACP Bridge

| Type / Symbol | Location | Purpose |
|---|---|---|
| `serveAcpGateway(opts)` | `src/acp/server.ts` | Entry point; connects to the gateway via `GatewayClient` and starts the ACP server loop |
| `AcpGatewayAgent` | `src/acp/translator.ts` | Implements the `@agentclientprotocol/sdk` `Agent` interface; translates every ACP message type to gateway operations |
| `resolveGatewayConnectionAuth()` | `src/acp/server.ts` | Resolves gateway credentials before the ACP server connects |
| `MAX_PROMPT_BYTES` | `src/acp/translator.ts` | `2 * 1024 * 1024` (2 MB) — hard cap on incoming prompt size as anti-DoS measure |
| `ACP_GATEWAY_DISCONNECT_GRACE_MS` | `src/acp/server.ts` | `5000` ms — grace window before a gateway disconnect is treated as fatal |
| ACP config options | `src/acp/translator.ts` | `thought_level`, `fast_mode`, `verbose_level`, `reasoning_level`, `response_usage`, `elevated_level` |

**ACP message types handled by `AcpGatewayAgent`:**

| Message Type | Effect |
|---|---|
| `InitializeRequest` | Validates client capabilities and returns server info |
| `AuthenticateRequest` | Forwards credentials to the gateway auth layer |
| `NewSessionRequest` | Creates a new `acp:`-namespaced session via the session system |
| `LoadSessionRequest` | Reattaches an ACP client to an existing named session |
| `ListSessionsRequest` | Returns all `acp:` sessions visible to the caller |
| `PromptRequest` | Submits a prompt into the active session; enforces `MAX_PROMPT_BYTES` |
| `CancelNotification` | Sends a cancellation signal into the running turn |
| `SetSessionConfigOptionRequest` | Updates one of the six exposed config knobs for the session |
| `SetSessionModeRequest` | Switches the session's operating mode (e.g. interactive vs. batch) |

## Architecture

### MCP Bridge: Channel-as-Tool

The MCP bridge makes OpenClaw channels appear as first-class MCP tools. When `createOpenClawChannelMcpServer` is called, it instantiates an `OpenClawChannelBridge` that maintains a live `GatewayClient` connection. `registerChannelMcpTools` then reads the channel registry and creates one MCP tool entry per channel, with input schemas derived from the channel's parameter definition. From that point on, the `McpServer` handles all JSON-RPC plumbing; the bridge's role is to translate `tools/call` requests into gateway channel invocations and stream the results back.

The `ClaudePermissionRequestSchema` notification path is a secondary concern: when Claude Desktop sends an approval request (for example, to execute a shell command on a node host), the handler intercepts the MCP notification and routes it through the gateway permission pipeline so the same approval UI and policy rules apply regardless of the entry point.

The gateway also starts a loopback MCP HTTP server (`src/gateway/mcp-http.ts`) so the agent runtime itself can reach MCP tool endpoints internally without requiring an external host process. This allows the same tool-calling surface to be used from both Claude Desktop and from scheduled or programmatic agent turns.

### ACP Bridge: Session-Multiplexing Agent

The ACP bridge exposes a single `AcpGatewayAgent` that satisfies the `@agentclientprotocol/sdk` `Agent` contract. It holds no session state itself; instead, every ACP session maps to a gateway session keyed as `acp:<identifier>`. This namespacing ensures ACP sessions are visible to the gateway's session management and reaping logic without being confused with interactive or cron sessions.

The six config options (`thought_level`, `fast_mode`, `verbose_level`, `reasoning_level`, `response_usage`, `elevated_level`) are a curated projection of the full gateway session config surface. ACP clients can adjust these via `SetSessionConfigOptionRequest` without gaining access to internal or privileged configuration knobs. The `MAX_PROMPT_BYTES` guard (2 MB) is enforced at the ACP layer before the payload reaches the gateway, preventing DoS conditions from oversized prompt submissions.

The disconnect grace period (`ACP_GATEWAY_DISCONNECT_GRACE_MS = 5000 ms`) allows the bridge to tolerate transient gateway reconnections without surfacing errors to the ACP client. During the grace window the bridge buffers or holds pending requests; if the gateway does not reconnect within the window the bridge propagates a session error.

## Runtime Behavior

### MCP Server Startup

1. The calling process (e.g. Claude Desktop) spawns the MCP bridge as a subprocess.
2. `createOpenClawChannelMcpServer(opts)` is invoked; it creates an `OpenClawChannelBridge` and calls `GatewayClient.connect()` using the provided auth options.
3. `registerChannelMcpTools(server, bridge)` iterates over all registered channels and registers a typed MCP tool for each one.
4. A `StdioServerTransport` is attached to `McpServer`; the server begins listening on stdin/stdout for JSON-RPC messages from the host.
5. Inbound `tools/call` requests are dispatched through the bridge to the gateway channel pipeline. Results are returned as MCP tool responses.
6. If a `ClaudePermissionRequestSchema` notification arrives, the handler routes the approval request to the gateway and waits for a response before returning to the MCP host.

### ACP Server Startup and Request Lifecycle

1. `serveAcpGateway(opts)` calls `resolveGatewayConnectionAuth()` to retrieve credentials, then opens a `GatewayClient` connection.
2. An `AcpGatewayAgent` instance is constructed and registered with the `@agentclientprotocol/sdk` server runtime.
3. On `InitializeRequest`, the agent returns capability metadata; on `AuthenticateRequest`, it forwards credentials to the gateway.
4. On `NewSessionRequest`, the agent creates a gateway session with an `acp:`-prefixed key and returns the session handle to the client.
5. On `PromptRequest`, the agent checks the payload size against `MAX_PROMPT_BYTES` (2 MB), then submits the prompt to the gateway session and streams response events back via the ACP event channel.
6. Config changes via `SetSessionConfigOptionRequest` are applied to the gateway session immediately and take effect on the next prompt turn.
7. If the gateway connection drops, the bridge enters a 5 000 ms grace window. A reconnected gateway resumes pending requests; a failure beyond the window terminates the affected sessions.

## Source Files

| File | Purpose |
|---|---|
| `src/mcp/channel-server.ts` | MCP server factory (`createOpenClawChannelMcpServer`), `StdioServerTransport` wiring, `ClaudePermissionRequestSchema` notification handler |
| `src/mcp/channel-bridge.ts` | `OpenClawChannelBridge` — `GatewayClient`-backed bridge between MCP tool calls and OpenClaw channels |
| `src/mcp/channel-tools.ts` | `registerChannelMcpTools` — builds the MCP tool catalog from registered channels |
| `src/mcp/channel-shared.ts` | Shared constants and helper types used across the MCP bridge modules |
| `src/gateway/mcp-http.ts` | Internal loopback MCP HTTP server started by the gateway for in-process tool use |
| `src/acp/server.ts` | `serveAcpGateway` entry point, `resolveGatewayConnectionAuth`, `ACP_GATEWAY_DISCONNECT_GRACE_MS` |
| `src/acp/translator.ts` | `AcpGatewayAgent` — implements the ACP `Agent` interface; `MAX_PROMPT_BYTES`; config option mapping |
| `src/acp/session.ts` | ACP session lifecycle management; `acp:` namespace enforcement |
| `src/acp/event-mapper.ts` | Maps gateway session events to ACP response event shapes |
| `src/acp/session-mapper.ts` | Translates ACP session identifiers to gateway session keys |
| `src/acp/types.ts` | Shared TypeScript types for the ACP subsystem |

## See Also

- [Gateway Control Plane](gateway-control-plane.md)
- [Channel System](channel-system.md)
- [Plugin Platform](plugin-platform.md)
- [Pluginized Capability Delivery](../concepts/pluginized-capability-delivery.md)
- [Inbound Message to Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
