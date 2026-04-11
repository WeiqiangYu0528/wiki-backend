# Gateway as Control Plane

## Overview

The gateway is the single stateful authority for the entire OpenClaw runtime. All channels, clients, sessions, plugins, cron jobs, approvals, and external bridges connect to it — not to each other. This means the gateway is not merely a WebSocket relay; it is the policy enforcement point, the session registry, the plugin activation coordinator, and the event distribution hub. The README's statement that "The Gateway is just the control plane — the product is the assistant" captures this precisely: channels and AI providers change, but the gateway's role as coordinator remains constant.

## Mechanism

### Single Point of Authority

`startGatewayServer()` in `src/gateway/server.impl.ts` is the composition root for everything runtime-stateful:

| Responsibility | Where |
|----------------|-------|
| Config loading and validation | `loadConfig()`, `applyConfigOverrides()` |
| Plugin registry construction and activation | `loadGatewayStartupPlugins()`, `setActivePluginRegistry()` |
| Channel manager startup | `createChannelManager()` — supervised per-account loops |
| Auth surface evaluation | `evaluateGatewayAuthSurfaceStates()` |
| Session lifecycle tracking | `onSessionLifecycleEvent()` subscribers |
| Cron service integration | `buildGatewayCronService()` |
| MCP loopback server | `startMcpLoopbackServer()` |
| Node/device registry | `NodeRegistry` |
| WebSocket handler attachment | `attachGatewayWsHandlers()` |
| Method handler registration | `coreGatewayHandlers` + plugin handlers |
| Control UI serving | `handleControlUiRequest()` |

No other subsystem holds equivalent authority. Channel plugins, ACP/MCP bridges, and CLI clients all acquire capabilities by calling gateway methods over the WebSocket protocol.

### WebSocket Frame Protocol

Every client — CLI, mobile app, Control UI, ACP bridge — speaks the same protocol:

```
ConnectParams → HelloOk (snapshot of current state)
RequestFrame (method call) ↔ ResponseFrame (result or error)
EventFrame (push: session events, agent output, channel status)
```

The `features.methods` array in `HelloOk` declares which gateway methods are available, allowing clients to degrade gracefully when running against older gateway versions.

### Config Reload Without Restart

`startGatewayConfigReloader()` watches `openclaw.yml` for changes. On change, it:
1. Re-loads and validates config.
2. Re-evaluates auth surface states.
3. Re-activates the plugin registry (with optional deferred channel loading).
4. Updates channel manager state for any added/removed accounts.

Clients receive an `EventFrame` with `GATEWAY_EVENT_UPDATE_AVAILABLE` when config changes affect visible state.

### Secrets and Auth Surface Management

`GATEWAY_AUTH_SURFACE_PATHS` defines the paths and their auth requirements. `evaluateGatewayAuthSurfaceStates()` computes which surfaces need tokens, passwords, or Tailscale at startup and on reload. The rate limiter (`createAuthRateLimiter()`) guards auth endpoints against brute force.

### Heartbeat and Health

`startHeartbeatRunner()` drives periodic heartbeat events. Channel plugins can declare `ChannelHeartbeatAdapter` to receive wakeup events for polling-based channels. `onHeartbeatEvent()` subscribers in the gateway keep maintenance timers and stale-session reaping running.

## Invariants

1. **All sessions are gateway-owned.** No client persists session state independently.
2. **All plugin registrations go through the gateway.** Plugins cannot inject behavior into agent execution without being in the active registry.
3. **All method access is gated by auth.** `ResolvedGatewayAuth` is evaluated on every WebSocket handshake; device tokens are validated by `device-auth.ts`.
4. **Event ordering is guaranteed within a connection.** `seq` on `EventFrame` increments monotonically; clients can detect missed events.

## Involved Entities

- [Gateway Control Plane](../entities/gateway-control-plane.md) — the concrete implementation
- [Plugin Platform](../entities/plugin-platform.md) — activated and managed by the gateway
- [Channel System](../entities/channel-system.md) — channel accounts started by the gateway
- [Session System](../entities/session-system.md) — session events subscribed by the gateway
- [Automation and Cron](../entities/automation-and-cron.md) — cron service integrated into gateway startup

## Source Evidence

| File | Contribution |
|------|-------------|
| `src/gateway/server.impl.ts` | `startGatewayServer()` — full composition root |
| `src/gateway/auth.ts` | `ResolvedGatewayAuth`, `GatewayAuthResult`, auth modes |
| `src/gateway/server-methods.ts` | `coreGatewayHandlers` — all method registrations |
| `src/gateway/server-ws-runtime.ts` | `attachGatewayWsHandlers()` — WebSocket binding |
| `src/gateway/config-reload.ts` | `startGatewayConfigReloader()` — hot-reload loop |
| `src/gateway/server-channels.ts` | `createChannelManager()` — supervised channel account loops |
| `src/gateway/node-registry.ts` | `NodeRegistry` — paired device tracking |
| `src/secrets/runtime-gateway-auth-surfaces.ts` | `GATEWAY_AUTH_SURFACE_PATHS`, `evaluateGatewayAuthSurfaceStates()` |
| `src/gateway/protocol/schema/frames.ts` | `ConnectParams`, `HelloOk`, `GatewayFrame` wire schemas |

## See Also

- [Gateway Control Plane](../entities/gateway-control-plane.md)
- [Plugin Platform](../entities/plugin-platform.md)
- [Multi-Channel Session Routing](multi-channel-session-routing.md)
- [Inbound Message to Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
- [Onboarding to Live Gateway Flow](../syntheses/onboarding-to-live-gateway-flow.md)
