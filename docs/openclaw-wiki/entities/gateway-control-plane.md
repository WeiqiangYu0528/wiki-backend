# Gateway Control Plane

## Overview

The Gateway is the operational core of OpenClaw. It is a long-running process that owns all runtime state: it authenticates control-plane clients, bootstraps channel and provider plugins, manages sessions, serves the Control UI, hosts the MCP loopback server, and coordinates paired node/device connections. The README frames this explicitly — "The Gateway is just the control plane — the product is the assistant" — because channels, apps, and AI agents all orbit the gateway rather than bypassing it.

In architectural terms the Gateway is a WebSocket server that speaks a typed binary-safe frame protocol. Every client (CLI, mobile app, Control UI, channel plugin) connects by sending a `ConnectParams` frame, receives a `HelloOk` acknowledgment, and then exchanges `RequestFrame` / `ResponseFrame` / `EventFrame` messages for the lifetime of the session.

## Key Types and Interfaces

### Wire-protocol frames (`src/gateway/protocol/schema/frames.ts`)

```ts
// Sent by client on connect; negotiates protocol version and carries auth.
export const ConnectParamsSchema = Type.Object({
  minProtocol: Type.Integer({ minimum: 1 }),
  maxProtocol: Type.Integer({ minimum: 1 }),
  client: Type.Object({
    id: GatewayClientIdSchema,
    version: NonEmptyString,
    platform: NonEmptyString,
    mode: GatewayClientModeSchema,
    ...
  }),
  auth: Type.Optional(Type.Object({
    token: Type.Optional(Type.String()),
    deviceToken: Type.Optional(Type.String()),
    ...
  })),
  ...
});

// Server reply after successful handshake.
export const HelloOkSchema = Type.Object({
  type: Type.Literal("hello-ok"),
  protocol: Type.Integer({ minimum: 1 }),
  server: Type.Object({ version: NonEmptyString, connId: NonEmptyString }),
  features: Type.Object({ methods: Type.Array(NonEmptyString), events: Type.Array(NonEmptyString) }),
  snapshot: SnapshotSchema,
  ...
});

// All traffic is one of three discriminated frame shapes.
export const GatewayFrameSchema = Type.Union(
  [RequestFrameSchema, ResponseFrameSchema, EventFrameSchema],
  { discriminator: "type" },
);
```

`RequestFrame` carries `{ type: "req", id, method, params? }`.
`ResponseFrame` carries `{ type: "res", id, ok, payload?, error? }`.
`EventFrame` carries `{ type: "event", event, payload?, seq?, stateVersion? }`.

### Type exports (`src/gateway/protocol/schema/types.ts`)

The full typed catalogue of all Gateway methods is derived from the same TypeBox schemas:

```ts
export type ConnectParams     = SchemaType<"ConnectParams">;
export type HelloOk           = SchemaType<"HelloOk">;
export type RequestFrame      = SchemaType<"RequestFrame">;
export type ResponseFrame     = SchemaType<"ResponseFrame">;
export type EventFrame        = SchemaType<"EventFrame">;
export type SessionsSendParams = SchemaType<"SessionsSendParams">;
export type SessionsCreateParams = SchemaType<"SessionsCreateParams">;
// ... plus ~60 more method-specific param/result types
```

## Architecture

`startGatewayServer()` in `server.impl.ts` is the composition root. It:

1. Loads and validates `openclaw.yml` via `loadConfig()`.
2. Resolves auth surfaces and rate-limiters.
3. Calls `resolveGatewayStartupPluginIds()` to determine which channel and provider plugins load at startup vs. on-demand.
4. Calls `createPluginRuntime()` and `setActivePluginRegistry()` to activate the plugin layer.
5. Calls `createChannelManager()` (`server-channels.ts`) which starts each enabled channel account's polling/streaming loop with a supervised backoff policy (`CHANNEL_RESTART_POLICY: { initialMs: 5_000, maxMs: 5 * 60_000, factor: 2 }`).
6. Calls `startMcpLoopbackServer()` for MCP tool integrations.
7. Attaches WebSocket handlers via `attachGatewayWsHandlers()`.
8. Registers method handlers via `server-methods.ts`.

Channel manager state is held as a `ChannelRuntimeStore` — four maps tracking abort controllers, startup promises, live tasks, and account snapshots:

```ts
type ChannelRuntimeStore = {
  aborts:   Map<string, AbortController>;
  starting: Map<string, Promise<void>>;
  tasks:    Map<string, Promise<unknown>>;
  runtimes: Map<string, ChannelAccountSnapshot>;
};
```

The snapshot type that accumulates across all running channels is:

```ts
export type ChannelRuntimeSnapshot = {
  channels:        Partial<Record<ChannelId, ChannelAccountSnapshot>>;
  channelAccounts: Partial<Record<ChannelId, Record<string, ChannelAccountSnapshot>>>;
};
```

### How channels register

Each channel plugin is a `ChannelPlugin` object (see `types.plugin.ts`) registered in the plugin catalog. On startup, `createChannelManager()` calls `listChannelPlugins()` to enumerate all enabled channels, then starts an account-scoped loop per configured account. The loop calls the plugin's `gateway.startAccount(ctx)` adapter — a long-running async function that receives inbound messages and emits them into the reply dispatch pipeline. The gateway wraps each loop with the supervised backoff policy so crashes restart automatically up to `MAX_RESTART_ATTEMPTS = 10`.

### Request / response routing

Method calls arrive as `RequestFrame` messages, are dispatched by name in `server-methods.ts`, and reply as `ResponseFrame` messages with the same `id`. Events (agent output, session updates, channel status changes) are pushed as `EventFrame` messages carrying a monotonically increasing `seq` and an optional `stateVersion` for snapshot reconciliation.

## Source Files

| File | Purpose |
|------|---------|
| `src/gateway/server.impl.ts` | Composition root; `startGatewayServer()` entry point |
| `src/gateway/server.ts` | Public re-export barrel |
| `src/gateway/server-methods.ts` | Registers all control-plane method handlers |
| `src/gateway/server-channels.ts` | Channel manager; supervised per-account start loops |
| `src/gateway/server-ws-runtime.ts` | WebSocket attachment and runtime event serving |
| `src/gateway/server-plugin-bootstrap.ts` | Startup and deferred plugin loading |
| `src/gateway/server-cron.ts` | Cron service integration |
| `src/gateway/mcp-http.ts` | MCP loopback server startup |
| `src/gateway/protocol/schema/frames.ts` | Wire-protocol frame schemas (`ConnectParams`, `HelloOk`, `GatewayFrame`) |
| `src/gateway/protocol/schema/types.ts` | Derived TypeScript types for all protocol shapes |
| `src/gateway/protocol/schema/*.ts` | Per-domain schemas (sessions, config, agents, nodes, etc.) |
| `src/gateway/protocol/index.ts` | Validator index; runtime AJV schema compilation |

## See Also

- [Channel System](channel-system.md)
- [Routing System](routing-system.md)
- [Session System](session-system.md)
- [Gateway as Control Plane](../concepts/gateway-as-control-plane.md)
- [Inbound Message to Agent Reply Flow](../syntheses/inbound-message-to-agent-reply-flow.md)
